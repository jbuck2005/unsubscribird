"""BioCLIP 2 image embeddings (CPU) + zero-shot suggestions, and the background worker that fills them in.

A frame is 16:9 but the model sees a 224x224 square, and its own preprocessing would cut off the sides
(where birds often perch). So every frame is embedded as four views:
  full  - the whole frame letterboxed into a square (context, small birds get tiny)
  L/C/R - full-height squares from the left, centre and right (birds big enough to see detail)
The classifier uses the view that looks most like an animal (by zero-shot score) plus the full view.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np

from .config import Settings
from .db import DB

LOG = logging.getLogger("wbs.embed")

EMBEDDER = "bioclip-2"
EMB_VERSION = 2          # 2 = adds a 5th view: a square crop around the detected bird (when one is found)
HF_ID = "hf-hub:imageomics/bioclip-2"
VIEW_NAMES = ("full", "L", "C", "R")
NON_BIRD_TEXT = {
    "Empty": "a photo of an empty bird feeder with seeds.",
    "Squirrel": "a photo of a squirrel, Sciuridae.",
    "Chipmunk": "a photo of Tamias striatus, chipmunk.",
    "Other animal": "a photo of a mammal.",
}


def species_text(name: str, scientific: str, kind: str) -> str | None:
    if kind == "other":
        return NON_BIRD_TEXT.get(name)            # "Unknown bird" has no useful text
    return f"a photo of {scientific}, {name}." if scientific else f"a photo of a {name}, a bird."


def make_views(img, crop_box: tuple[int, int, int, int] | None = None):
    """PIL image -> [full (letterboxed square), left, centre, right squares] (+ [bird crop])."""
    from PIL import Image
    w, h = img.size
    side = min(w, h)
    full = Image.new("RGB", (max(w, h), max(w, h)))
    full.paste(img, ((max(w, h) - w) // 2, (max(w, h) - h) // 2))
    if w >= h:
        crops = [img.crop((x, 0, x + side, side)) for x in (0, (w - side) // 2, w - side)]
    else:
        crops = [img.crop((0, y, side, y + side)) for y in (0, (h - side) // 2, h - side)]
    views = [full, *crops]
    if crop_box:
        views.append(img.crop(crop_box))
    return views


class Embedder:
    """Lazy wrapper: torch/open_clip are only imported when the first image is embedded."""

    def __init__(self, threads: int = 4) -> None:
        self.threads = threads
        self._model = None
        self._lock = threading.Lock()
        self._text_key: tuple = ()
        self._text: tuple[list[str], np.ndarray] | None = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import open_clip
        import torch
        torch.set_num_threads(self.threads)
        t = time.time()
        model, _, preprocess = open_clip.create_model_and_transforms(HF_ID)
        model.eval()
        self._torch, self._model, self._preprocess = torch, model, preprocess
        self._tokenizer = open_clip.get_tokenizer(HF_ID)
        LOG.info("BioCLIP 2 loaded in %.0fs", time.time() - t)

    def embed_image(self, path, crop_box: tuple[int, int, int, int] | None = None, img=None) -> np.ndarray:
        """Returns float32 (4 or 5, dim), L2-normalised; the 5th view is the bird crop if a box is given."""
        from PIL import Image
        with self._lock:
            self._load()
            img = img or Image.open(path).convert("RGB")
            batch = self._torch.stack([self._preprocess(v) for v in make_views(img, crop_box)])
            with self._torch.no_grad():
                e = self._model.encode_image(batch).float()
            e = e / e.norm(dim=-1, keepdim=True)
            return e.numpy().astype(np.float32)

    def text_embeddings(self, species: list[tuple[str, str, str]]) -> tuple[list[str], np.ndarray]:
        """species rows (name, scientific, kind) -> (names, (n, dim)); cached until the list changes."""
        key = tuple(species)
        with self._lock:
            if self._text is not None and key == self._text_key:
                return self._text
            self._load()
            names, texts = [], []
            for name, sci, kind in species:
                t = species_text(name, sci, kind)
                if t:
                    names.append(name)
                    texts.append(t)
            with self._torch.no_grad():
                e = self._model.encode_text(self._tokenizer(texts)).float()
            e = (e / e.norm(dim=-1, keepdim=True)).numpy().astype(np.float32)
            self._text_key, self._text = key, (names, e)
            return self._text


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


def zero_shot(views: np.ndarray, names: list[str], text: np.ndarray, non_bird: set[str]) -> dict[str, Any]:
    """Zero-shot probabilities per view; picks the view that looks most like an animal."""
    probs = softmax(100.0 * views @ text.T)                 # (views, classes)
    empty = [i for i, n in enumerate(names) if n == "Empty"]
    animal = 1.0 - (probs[:, empty].sum(axis=1) if empty else 0.0)
    best_view = int(np.argmax(animal))
    p = probs[best_view]
    top = int(np.argmax(p))
    return {"view": best_view, "animal": float(animal[best_view]), "probs": p,
            "species": names[top], "confidence": float(p[top]), "bird": names[top] not in non_bird}


def frame_feature(views: np.ndarray, best_view: int) -> np.ndarray:
    """Classifier input: the bird crop if there is one (5th view), else the most animal-like view,
    plus the full view (each L2-normalised) -> (2*dim,)."""
    focus = views[4] if views.shape[0] >= 5 else views[best_view]
    return np.concatenate([focus, views[0]]).astype(np.float32)


def to_blob(a: np.ndarray) -> bytes:
    return np.ascontiguousarray(a, dtype=np.float32).tobytes()


def from_blob(b: bytes, views: int, dim: int) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32).reshape(views, dim)


class EmbedWorker:
    """Embeds every (non-rejected) frame, newest first, then adds a BioCLIP zero-shot suggestion per visit
    and, if a trained model is active, the model's prediction."""

    def __init__(self, settings: Settings, db: DB, embedder: Embedder, predictor=None, detector=None) -> None:
        self.s, self.db, self.embedder, self.detector = settings, db, embedder, detector
        self.predictor = predictor          # callable(trace_id) -> None, set by the trainer
        self.stop = threading.Event()
        self.stats: dict[str, Any] = {"embedded": 0, "seconds_per_frame": None, "last_error": "", "state": "idle",
                                      "skipped": 0}
        self.bad: set[int] = set()      # frames that could not be processed (skipped until restart)

    def start(self) -> None:
        threading.Thread(target=self._loop, name="embed", daemon=True).start()

    def species_rows(self) -> list[tuple[str, str, str]]:
        return [(r["name"], r["scientific"] or "", r["kind"])
                for r in self.db.q("SELECT name, scientific, kind FROM species WHERE active=1 ORDER BY name")]

    def _loop(self) -> None:
        while not self.stop.is_set():
            wait = 20
            try:
                if self.run_once():
                    wait = 1
            except Exception as err:
                self.stats["last_error"] = str(err)[:200]
                self.stats["state"] = "error"
                LOG.exception("Embedding error")
                wait = 120
            self.stop.wait(wait)

    def run_once(self, limit: int = 8) -> int:
        # Quiet visits (nothing moved) are only embedded once confirmed: training needs them, prediction doesn't.
        rows = self.db.q("""SELECT f.*, v.ts FROM frames f JOIN visits v USING(trace_id)
                            LEFT JOIN embeddings e ON e.frame_id=f.id
                            LEFT JOIN labels l ON l.trace_id=v.trace_id
                            WHERE (e.frame_id IS NULL OR e.version < ?) AND f.rejected=0
                              AND v.status IN ('frames','prelabelled') AND (v.quiet=0 OR l.trace_id IS NOT NULL)
                            ORDER BY (e.frame_id IS NOT NULL), v.ts DESC, f.id LIMIT ?""", EMB_VERSION,
                         limit + len(self.bad))
        rows = [f for f in rows if f["id"] not in self.bad]
        if not rows:
            self.stats["state"] = "idle"
            return 0
        self.stats["state"] = "embedding"
        touched = set()
        for f in rows:
            t = time.time()
            try:
                e = self.embed_frame(f)
            except Exception as err:   # a broken image must not block every frame behind it
                self.bad.add(f["id"])
                self.stats["skipped"] += 1
                self.stats["last_error"] = f"frame {f['id']}: {err}"[:200]
                LOG.warning("Skipping frame %s (%s): %s", f["id"], f["path"], err)
                continue
            with self.db.tx() as c:
                c.execute("INSERT OR REPLACE INTO embeddings(frame_id, embedder, views, dim, data, created, version) "
                          "VALUES (?,?,?,?,?,?,?)", (f["id"], EMBEDDER, e.shape[0], e.shape[1], to_blob(e),
                                                     time.time(), EMB_VERSION))
            self.stats["embedded"] += 1
            self.stats["seconds_per_frame"] = round(time.time() - t, 2)
            touched.add(f["trace_id"])
        for trace in touched:
            self.suggest_visit(trace)
        return len(rows)

    def embed_frame(self, f) -> np.ndarray:
        """Detect the bird (if a detector is configured), store the box, embed with the crop as 5th view."""
        from PIL import Image
        from .detect import square_crop_box
        img = Image.open(self.s.image_dir / f["path"]).convert("RGB")
        crop = None
        if self.detector is not None:
            det = self.detector.find(img, f["motion_box"] if "motion_box" in f.keys() else None)
            with self.db.tx() as c:
                c.execute("DELETE FROM detections WHERE frame_id=?", (f["id"],))
                if det:
                    b = det["box"]
                    c.execute("""INSERT INTO detections(frame_id, source, label, score, x1, y1, x2, y2, created)
                                 VALUES (?,?,?,?,?,?,?,?,?)""",
                              (f["id"], det["source"], det["label"], det["score"], *b, time.time()))
            if det:
                crop = square_crop_box(det["box"], *img.size)
        return self.embedder.embed_image(None, crop, img=img)

    def visit_views(self, trace_id: str) -> list[tuple[int, np.ndarray]]:
        rows = self.db.q("""SELECT e.* FROM embeddings e JOIN frames f ON f.id=e.frame_id
                            WHERE f.trace_id=? AND f.rejected=0 AND f.kind='clip'""", trace_id)
        if not rows:   # snapshot-only visit
            rows = self.db.q("""SELECT e.* FROM embeddings e JOIN frames f ON f.id=e.frame_id
                                WHERE f.trace_id=? AND f.rejected=0""", trace_id)
        return [(r["frame_id"], from_blob(r["data"], r["views"], r["dim"])) for r in rows]

    def suggest_visit(self, trace_id: str) -> None:
        """Zero-shot BioCLIP suggestion for the whole visit (average of each frame's best view)."""
        frames = self.visit_views(trace_id)
        if not frames:
            return
        names, text = self.embedder.text_embeddings(self.species_rows())
        non_bird = {r[0] for r in self.species_rows() if r[2] == "other"}
        zs = [zero_shot(v, names, text, non_bird) for _, v in frames]
        mean = np.mean([z["probs"] for z in zs], axis=0)
        top = int(np.argmax(mean))
        result = {"bird_present": names[top] not in non_bird, "species": names[top],
                  "confidence": round(float(mean[top]), 3),
                  "notes": "BioCLIP 2 zero-shot, " + ", ".join(f"{names[i]} {mean[i]:.0%}" for i in np.argsort(-mean)[:3])}
        with self.db.tx() as c:
            c.execute("DELETE FROM suggestions WHERE trace_id=? AND source='bioclip'", (trace_id,))
        self.db.add_suggestion(trace_id, None, "bioclip", EMBEDDER, result, "")
        if self.predictor:
            self.predictor(trace_id)
