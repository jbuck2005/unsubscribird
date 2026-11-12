"""Pre-label frames with a vision model in LM Studio (suggestions only; a person confirms every label)."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from typing import Any

import requests

from .config import Settings
from .db import DB
from .species import NON_BIRD

NON_BIRD_NAMES = {n for n, _, _ in NON_BIRD}

LOG = logging.getLogger("wbs.prelabel")

PROMPT = (
    "You are an expert ornithologist. This frame is from a bird-feeder camera in {region}. "
    "Identify the animal(s) on or near the feeder. Reply with ONLY a JSON object: "
    '{{"bird_present": true|false, "count": int, "species": "common name or null", '
    '"scientific_name": "or null", "confidence": 0-1, "other_animal": "e.g. squirrel or null", '
    '"notes": "short reason"}}. If several species are visible, give the most prominent one and mention the others in notes.'
)


def parse_json(text: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a model reply (handles <think> blocks and code fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    for m in re.finditer(r"\{.*\}", text, flags=re.S):
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except ValueError:
            continue
    return None


def consensus(suggestions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Combine per-frame suggestions into one suggested label for the visit."""
    if not suggestions:
        return None
    weights: dict[str, float] = defaultdict(float)
    votes: Counter = Counter()
    for s in suggestions:
        if s.get("bird_present") and s.get("species"):
            name = s["species"].strip()
        elif s.get("other_animal"):
            name = "Squirrel" if "squirrel" in s["other_animal"].lower() else (
                "Chipmunk" if "chipmunk" in s["other_animal"].lower() else "Other animal")
        elif s.get("bird_present"):
            name = "Unknown bird"
        else:
            name = "Empty"
        votes[name] += 1
        weights[name] += float(s.get("confidence") or 0.5)
    # Anything seen in any frame beats "Empty" frames (the bird may have left mid-clip);
    # on a tie between a bird and another animal, the bird wins.
    seen = {n: w for n, w in weights.items() if n != "Empty"}
    pool = seen or weights
    best = max(pool, key=lambda n: (round(pool[n], 6), votes[n], n not in NON_BIRD_NAMES))
    return {"species": best, "votes": votes[best], "frames": len(suggestions),
            "confidence": round(weights[best] / max(votes[best], 1), 2)}


class LMStudio:
    def __init__(self, settings: Settings) -> None:
        self.s = settings
        self.http = requests.Session()
        self.status = "unknown"

    def pick_model(self) -> str | None:
        if not self.s.lmstudio_url:
            self.status = "off: UNSUB_AI_HOST isn't set"
            return None
        try:
            models = self.http.get(f"{self.s.lmstudio_url}/api/v0/models", timeout=10).json()["data"]
        except (requests.RequestException, ValueError, KeyError) as err:
            self.status = f"unreachable ({err.__class__.__name__})"
            return None
        vlms = [m for m in models if m.get("type") == "vlm"]
        if self.s.lmstudio_model:
            m = next((m for m in vlms if m["id"] == self.s.lmstudio_model), None)
            if not m:
                self.status = f"model {self.s.lmstudio_model} not found"
                return None
            if self.s.lmstudio_require_loaded and m.get("state") != "loaded":
                self.status = f"waiting: {m['id']} is not loaded"
                return None
            self.status = f"ready: {m['id']}"
            return m["id"]
        loaded = [m for m in vlms if m.get("state") == "loaded"]
        if not loaded:
            self.status = "waiting: no vision model loaded"
            return None
        self.status = f"ready: {loaded[0]['id']}"
        return loaded[0]["id"]

    def ask(self, model: str, jpeg: bytes) -> tuple[dict[str, Any] | None, str]:
        body = {"model": model, "temperature": 0, "max_tokens": 2000, "messages": [{"role": "user", "content": [
            {"type": "text", "text": PROMPT.format(region=self.s.region)},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}}]}]}
        r = self.http.post(f"{self.s.lmstudio_url}/v1/chat/completions", json=body, timeout=300)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"].get("content") or ""
        return parse_json(text), text


class Prelabeler:
    def __init__(self, settings: Settings, db: DB) -> None:
        self.s, self.db = settings, db
        self.lm = LMStudio(settings)
        self.stats = {"done": 0, "last_error": "", "seconds_per_frame": None}
        self.stop = threading.Event()
        self.paused = False             # set while a model comparison uses LM Studio
        self.after_visit = None         # callable(trace_id) once LM Studio has seen a visit, e.g. re-decide it

    def start(self) -> None:
        threading.Thread(target=self._loop, name="prelabel", daemon=True).start()

    def next_model(self) -> str | None:
        """The model to pre-label with now, or None while paused or none is ready."""
        if self.paused:
            return None
        if self.s.prelabel_paused:
            self.lm.status = "paused on the Settings page"
            return None
        return self.lm.pick_model()

    def _loop(self) -> None:
        while not self.stop.is_set():
            wait = 15
            try:
                model = self.next_model()
                if model is None:
                    wait = 120
                else:
                    self.run_once(model)
            except Exception as err:
                self.stats["last_error"] = str(err)[:200]
                LOG.exception("Pre-label error")
                wait = 60
            self.stop.wait(wait)

    def frames_to_label(self, trace_id: str) -> list:
        clip = self.db.q("""SELECT * FROM frames WHERE trace_id=? AND kind='clip' AND rejected=0
                            ORDER BY score DESC LIMIT ?""", trace_id, self.s.prelabel_frames)
        return clip or self.db.q("SELECT * FROM frames WHERE trace_id=? AND kind='snapshot' AND rejected=0", trace_id)

    def label_frame(self, trace_id: str, frame) -> dict[str, Any] | None:
        """Suggest a label for one frame right now (used when a person grabs a replacement frame)."""
        model = None if self.s.prelabel_paused else self.lm.pick_model()
        if model is None:
            return None
        result, raw = self.lm.ask(model, (self.s.image_dir / frame["path"]).read_bytes())
        self.db.add_suggestion(trace_id, frame["id"], "vlm", model, result or {}, raw[-4000:])
        return result

    def run_once(self, model: str, limit: int = 5) -> int:
        # Newest first: the review queue shows recent visits first.
        visits = self.db.q("SELECT trace_id FROM visits WHERE status='frames' ORDER BY ts DESC LIMIT ?", limit)
        for v in visits:
            for f in self.frames_to_label(v["trace_id"]):
                t = time.time()
                jpeg = (self.s.image_dir / f["path"]).read_bytes()
                result, raw = self.lm.ask(model, jpeg)
                self.db.add_suggestion(v["trace_id"], f["id"], "vlm", model, result or {}, raw[-4000:])
                self.stats["seconds_per_frame"] = round(time.time() - t, 1)
            self.db.set_visit(v["trace_id"], status="prelabelled")
            self.stats["done"] += 1
            if self.after_visit:
                try:
                    self.after_visit(v["trace_id"])
                except Exception:   # the suggestion is saved; Home Assistant catches up on the next refresh
                    LOG.exception("After-prelabel hook failed for %s", v["trace_id"])
        return len(visits)
