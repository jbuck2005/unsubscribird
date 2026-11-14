"""/healthz: is the app up, and (deep=1) do the models actually run?

A plain 200 from the web server says nothing about the models: after a library upgrade every OWL-ViT check can fail
while every page still loads. The deep check runs one real OWL-ViT detection and one BioCLIP 2 embedding on a small
built-in frame, so a deploy script can roll back an image whose models are broken.

The result is cached (TTL seconds) and only one check runs at a time, so polling it is cheap and an outside caller
can't make the models work harder than once per TTL. The first deep check after start-up loads both models, which
can take a minute on a slow machine. Errors are reported by type only; the details go to the log.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

LOG = logging.getLogger("unsub.health")
TTL = 60.0


def test_frame():
    """A small made-up frame: sky, a lawn and a brown blob. Nothing from a real camera."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (320, 240), (150, 190, 225))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 160, 320, 240), fill=(90, 140, 70))
    draw.ellipse((140, 110, 180, 150), fill=(120, 80, 50))
    return img


class DeepHealth:
    def __init__(self, detector, embedder, ttl: float = TTL, clock: Callable[[], float] = time.monotonic) -> None:
        self.detector, self.embedder = detector, embedder
        self.ttl, self.clock = ttl, clock
        self._lock = threading.Lock()
        self._result: dict[str, Any] | None = None
        self._at = 0.0

    def _run(self, name: str, fn) -> dict[str, Any]:
        t = time.perf_counter()
        try:
            fn()
        except Exception as err:   # anything a model call raises is a failed check, not a crashed endpoint
            LOG.warning("Deep health check: %s failed: %r", name, err)
            return {"ok": False, "error": type(err).__name__}
        return {"ok": True, "ms": round((time.perf_counter() - t) * 1000)}

    def _embed(self, img) -> None:
        e = self.embedder.embed_image(None, img=img)
        if getattr(e, "ndim", 0) != 2 or not e.shape[0] or not e.shape[1]:
            raise ValueError("unexpected embedding shape")

    def check(self) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            if self._result is not None and now - self._at < self.ttl:
                return {**self._result, "age_s": round(now - self._at)}
            img = test_frame()
            checks = {"owlvit": self._run("OWL-ViT", lambda: self.detector.owl(img)) if self.detector
                      else {"ok": True, "skipped": "detection is off"},
                      "bioclip": self._run("BioCLIP 2", lambda: self._embed(img))}
            self._result = {"ok": all(c["ok"] for c in checks.values()), "checks": checks}
            self._at = self.clock()
            return {**self._result, "age_s": 0}
