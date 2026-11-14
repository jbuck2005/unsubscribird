"""/healthz and its deep check: real model calls are faked; the point is the status codes, the cache and what the
public answer gives away."""
import numpy as np
from fastapi.testclient import TestClient

from wbs import main
from wbs.health import DeepHealth


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Det:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, 0

    def owl(self, img):
        self.calls += 1
        assert img.size == (320, 240)
        if self.fail:
            raise AttributeError("'OwlViTProcessor' object has no attribute 'post_process_object_detection'")
        return None


class Emb:
    def __init__(self, shape=(4, 768)):
        self.shape, self.calls = shape, 0

    def embed_image(self, path, crop_box=None, img=None):
        self.calls += 1
        assert path is None and img is not None
        return np.zeros(self.shape, np.float32)


def test_all_good_and_cached_for_the_ttl():
    clock, det, emb = Clock(), Det(), Emb()
    h = DeepHealth(det, emb, ttl=60, clock=clock)
    first = h.check()
    assert first["ok"] and first["checks"]["owlvit"]["ok"] and first["checks"]["bioclip"]["ok"]
    clock.t += 30
    again = h.check()
    assert again["ok"] and again["age_s"] == 30 and (det.calls, emb.calls) == (1, 1)
    clock.t += 31
    h.check()
    assert (det.calls, emb.calls) == (2, 2)


def test_a_broken_model_fails_with_only_the_error_type():
    r = DeepHealth(Det(fail=True), Emb()).check()
    assert not r["ok"]
    assert r["checks"]["owlvit"] == {"ok": False, "error": "AttributeError"}
    assert r["checks"]["bioclip"]["ok"]


def test_a_bad_embedding_fails():
    r = DeepHealth(Det(), Emb(shape=(0,))).check()
    assert not r["ok"] and r["checks"]["bioclip"] == {"ok": False, "error": "ValueError"}


def test_detection_off_is_skipped_not_failed():
    r = DeepHealth(None, Emb()).check()
    assert r["ok"] and r["checks"]["owlvit"]["skipped"]


def test_the_endpoint_needs_no_login_and_answers_503_when_broken(monkeypatch):
    c = TestClient(main.app)
    plain = c.get("/healthz")
    assert plain.status_code == 200 and plain.json() == {"ok": True, "version": main.version_label}
    monkeypatch.setattr(main, "health", DeepHealth(Det(), Emb()))
    assert c.get("/healthz?deep=1").status_code == 200
    monkeypatch.setattr(main, "health", DeepHealth(Det(fail=True), Emb()))
    bad = c.get("/healthz?deep=1")
    assert bad.status_code == 503 and not bad.json()["ok"]
    assert "post_process" not in bad.text   # no error messages to the public
