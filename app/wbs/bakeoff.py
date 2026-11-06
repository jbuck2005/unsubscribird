"""Compare LM Studio vision models against the user's confirmed labels (run on request from the Model page).

For each selected model, the same stratified sample of confirmed visits (2 frames each) is sent with the
pre-labelling prompt. Scores: visit accuracy (frame consensus vs the confirmed species), bird-present accuracy,
share of answers that were valid JSON, seconds per frame. LM Studio loads models just-in-time, which may unload
the model used for pre-labelling; pre-labelling is paused during the run and the original model is requested
again at the end.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
from collections import defaultdict
from typing import Any, Callable

from .db import DB
from .prelabel import LMStudio, Prelabeler, consensus
from .species import NON_BIRD

LOG = logging.getLogger("wbs.bakeoff")
NON_BIRD_NAMES = {n for n, _, _ in NON_BIRD}

SCHEMA = """
CREATE TABLE IF NOT EXISTS bakeoff (
    id INTEGER PRIMARY KEY, run INTEGER NOT NULL, created REAL NOT NULL, model TEXT NOT NULL,
    status TEXT NOT NULL, visits INTEGER, frames INTEGER, visit_accuracy REAL, bird_accuracy REAL,
    json_ok REAL, seconds_per_frame REAL, details TEXT, error TEXT
);
"""


def sample_visits(db: DB, per_species: int, total: int, seed: int = 0) -> list[dict[str, Any]]:
    """Up to `per_species` confirmed visits per species (newest first within a species, shuffled), capped."""
    by_species: dict[str, list] = defaultdict(list)
    for lab in db.q("SELECT l.* FROM labels l JOIN visits v USING(trace_id) WHERE v.excluded=0 ORDER BY l.updated DESC"):
        by_species[lab["species"]].append(lab)
    rnd = random.Random(seed)
    picked = []
    for sp in sorted(by_species):
        rows = by_species[sp][:per_species * 3]
        rnd.shuffle(rows)
        picked += rows[:per_species]
    rnd.shuffle(picked)
    out = []
    for lab in picked[:total]:
        ids = json.loads(lab["frame_ids"])
        frames = db.q(f"""SELECT * FROM frames WHERE id IN ({','.join('?' * len(ids))}) AND rejected=0
                          ORDER BY (kind='clip') DESC, score DESC LIMIT 2""", *ids) if ids else []
        if frames:
            out.append({"trace_id": lab["trace_id"], "species": lab["species"], "frames": frames})
    return out


def score(results: list[dict[str, Any]], canonical: Callable[[str | None], str | None]) -> dict[str, Any]:
    visits_right = birds_right = frames = parsed = 0
    secs = 0.0
    confusions = []
    for r in results:
        sugg = []
        for f in r["frames"]:
            frames += 1
            secs += f["seconds"]
            if f["result"] is not None:
                parsed += 1
                s = dict(f["result"])
                s["species"] = canonical(s.get("species"))
                sugg.append(s)
                truth_bird = r["species"] not in NON_BIRD_NAMES or r["species"] == "Unknown bird"
                birds_right += int(bool(s.get("bird_present")) == truth_bird)
        c = consensus(sugg)
        guess = c["species"] if c else None
        ok = (guess or "").lower() == r["species"].lower()
        visits_right += int(ok)
        if not ok:
            confusions.append({"trace_id": r["trace_id"], "label": r["species"], "model": guess})
    n = len(results)
    return {"visits": n, "frames": frames,
            "visit_accuracy": round(visits_right / n, 3) if n else None,
            "bird_accuracy": round(birds_right / parsed, 3) if parsed else None,
            "json_ok": round(parsed / frames, 3) if frames else None,
            "seconds_per_frame": round(secs / frames, 2) if frames else None,
            "mistakes": confusions[:40]}


class Bakeoff:
    def __init__(self, db: DB, lm: LMStudio, prelabeler: Prelabeler, image_dir,
                 canonical: Callable[[str | None], str | None]) -> None:
        self.db, self.lm, self.prelabeler, self.image_dir, self.canonical = db, lm, prelabeler, image_dir, canonical
        with db.tx() as c:
            c.executescript(SCHEMA)
        self.status: dict[str, Any] = {"state": "idle", "message": ""}
        self._lock = threading.Lock()

    def models(self) -> list[dict[str, Any]]:
        try:
            data = self.lm.http.get(f"{self.lm.s.lmstudio_url}/api/v0/models", timeout=10).json()["data"]
        except Exception as err:   # noqa: BLE001 - shown in the UI
            return [{"error": f"LM Studio unreachable: {err.__class__.__name__}"}]
        return [{"id": m["id"], "state": m.get("state"), "quantization": m.get("quantization")}
                for m in data if m.get("type") == "vlm"]

    def start(self, models: list[str], per_species: int = 6, total: int = 40) -> bool:
        if not models or not self._lock.acquire(blocking=False):
            return False
        threading.Thread(target=self._run, args=(models, per_species, total), name="bakeoff", daemon=True).start()
        return True

    def _run(self, models: list[str], per_species: int, total: int) -> None:
        original = next((m["id"] for m in self.models() if m.get("state") == "loaded"), None)
        run = int(time.time())
        self.prelabeler.paused = True
        try:
            sample = sample_visits(self.db, per_species, total)
            if not sample:
                raise ValueError("no confirmed visits to test against")
            for i, model in enumerate(models, 1):
                self.status = {"state": "running", "message": f"{model} ({i}/{len(models)}): loading / starting",
                               "run": run}
                with self.db.tx() as c:
                    rid = c.execute("INSERT INTO bakeoff(run, created, model, status) VALUES (?,?,?,?)",
                                    (run, time.time(), model, "running")).lastrowid
                try:
                    results = []
                    for k, visit in enumerate(sample, 1):
                        self.status["message"] = f"{model} ({i}/{len(models)}): visit {k}/{len(sample)}"
                        frames = []
                        for f in visit["frames"]:
                            t = time.time()
                            try:
                                result, _ = self.lm.ask(model, (self.image_dir / f["path"]).read_bytes())
                            except Exception as err:   # one bad answer shouldn't end the model's run
                                LOG.warning("bake-off %s: %s", model, err)
                                result = None
                            frames.append({"result": result, "seconds": time.time() - t})
                        results.append({**visit, "frames": frames})
                    s = score(results, self.canonical)
                    with self.db.tx() as c:
                        c.execute("""UPDATE bakeoff SET status='done', visits=?, frames=?, visit_accuracy=?, bird_accuracy=?,
                                     json_ok=?, seconds_per_frame=?, details=? WHERE id=?""",
                                  (s["visits"], s["frames"], s["visit_accuracy"], s["bird_accuracy"], s["json_ok"],
                                   s["seconds_per_frame"], json.dumps({"mistakes": s["mistakes"]}), rid))
                    LOG.info("Bake-off %s: visit accuracy %s on %d visits", model, s["visit_accuracy"], s["visits"])
                except Exception as err:
                    LOG.exception("Bake-off of %s failed", model)
                    with self.db.tx() as c:
                        c.execute("UPDATE bakeoff SET status='failed', error=? WHERE id=?", (str(err)[:300], rid))
            self.status = {"state": "done", "message": f"compared {len(models)} model(s) on {len(sample)} visits",
                           "run": run}
        except Exception as err:
            self.status = {"state": "failed", "message": str(err)[:300]}
        finally:
            if original:   # ask for the pre-labelling model again (LM Studio reloads it just-in-time)
                try:
                    self.status["message"] += f"; reloading {original}"
                    self.lm.http.post(f"{self.lm.s.lmstudio_url}/v1/chat/completions", timeout=600,
                                      json={"model": original, "max_tokens": 1,
                                            "messages": [{"role": "user", "content": "ok"}]})
                except Exception as err:   # noqa: BLE001
                    LOG.warning("Could not reload %s: %s", original, err)
            self.prelabeler.paused = False
            self._lock.release()

    def results(self) -> list[dict[str, Any]]:
        rows = self.db.q("SELECT * FROM bakeoff ORDER BY run DESC, visit_accuracy DESC LIMIT 60")
        return [{**dict(r), "details": json.loads(r["details"]) if r["details"] else None} for r in rows]
