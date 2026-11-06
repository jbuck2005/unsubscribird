"""Find the bird in a frame so the classifier can look at a crop instead of the whole feeder scene.

1. OWL-ViT (open-vocabulary detector, "a photo of a bird" / "a photo of a squirrel") on CPU, ~1 s per frame.
   Tested 2026-11-05 on feeder frames: finds Blue Jays reliably (also close-ups that a COCO detector called
   "person"), misses small birds like chickadees.
2. If it finds nothing, the largest moving region of the frame (computed by the frame picker) - that catches
   small birds that come and go; it can't see a bird that sits still for the whole clip, which OWL-ViT does.
(OWLv2 found the chickadee too but took 24 s per frame on a desktop CPU.)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

LOG = logging.getLogger("wbs.detect")
OWL_ID = "google/owlvit-base-patch32"
QUERIES = ["a photo of a bird", "a photo of a squirrel"]
LABELS = ["bird", "squirrel"]
MIN_SCORE = 0.12


def square_crop_box(box: list[float], width: int, height: int, margin: float = 0.3) -> tuple[int, int, int, int]:
    """Normalised [x1,y1,x2,y2] -> a square pixel box around it with a margin, kept inside the image."""
    x1, y1, x2, y2 = box[0] * width, box[1] * height, box[2] * width, box[3] * height
    side = max(x2 - x1, y2 - y1) * (1 + margin)
    side = max(min(side, min(width, height)), 32)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    left = min(max(cx - side / 2, 0), width - side)
    top = min(max(cy - side / 2, 0), height - side)
    return int(left), int(top), int(left + side), int(top + side)


class Detector:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._model is None:
            from transformers import OwlViTForObjectDetection, OwlViTProcessor
            t = time.time()
            self._proc = OwlViTProcessor.from_pretrained(OWL_ID)
            self._model = OwlViTForObjectDetection.from_pretrained(OWL_ID).eval()
            LOG.info("OWL-ViT loaded in %.0fs", time.time() - t)

    def owl(self, img) -> dict[str, Any] | None:
        """Best bird/squirrel box as {'label','score','box' (normalised)} or None."""
        import torch
        with self._lock:
            self._load()
            inputs = self._proc(text=[QUERIES], images=img, return_tensors="pt")
            with torch.no_grad():
                out = self._model(**inputs)
            res = self._proc.post_process_object_detection(out, threshold=MIN_SCORE,
                                                           target_sizes=torch.tensor([img.size[::-1]]))[0]
        if not len(res["scores"]):
            return None
        i = int(res["scores"].argmax())
        w, h = img.size
        x1, y1, x2, y2 = [float(v) for v in res["boxes"][i]]
        box = [max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h)]
        return {"label": LABELS[int(res["labels"][i])], "score": round(float(res["scores"][i]), 3), "box": box}

    def find(self, img, motion_box_json: str | None) -> dict[str, Any] | None:
        det = self.owl(img)
        if det:
            return {**det, "source": "owlvit"}
        if motion_box_json:
            return {"label": None, "score": None, "box": json.loads(motion_box_json), "source": "motion"}
        return None
