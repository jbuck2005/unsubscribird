"""Detector.owl against a processor shaped like transformers 5's, where OwlViTProcessor no longer has
post_process_object_detection (only its image_processor does). torch is faked: the tests don't install it."""
import contextlib
import sys
import types

from PIL import Image

from wbs import detect


class FakeTensor(list):
    def argmax(self):
        return max(range(len(self)), key=self.__getitem__)


def fake_torch():
    t = types.ModuleType("torch")
    t.no_grad = contextlib.nullcontext
    t.tensor = lambda v: v
    return t


class ImageProcessor:
    def __init__(self, found):
        self.found, self.calls = found, []

    def post_process_object_detection(self, outputs, threshold, target_sizes):
        self.calls.append((outputs, threshold, target_sizes))
        if not self.found:
            return [{"scores": FakeTensor(), "labels": FakeTensor(), "boxes": FakeTensor()}]
        return [{"scores": FakeTensor([0.2, 0.6]), "labels": FakeTensor([1, 0]),
                 "boxes": FakeTensor([[0, 0, 10, 10], [40, 30, 120, 90]])}]


class ProcessorV5:
    """Like transformers 5's OwlViTProcessor: no post_process_object_detection of its own."""
    def __init__(self, found=True):
        self.image_processor = ImageProcessor(found)

    def __call__(self, text, images, return_tensors):
        assert text == [detect.QUERIES] and return_tensors == "pt"
        return {"pixel_values": "px"}


def detector(monkeypatch, found=True):
    monkeypatch.setitem(sys.modules, "torch", fake_torch())
    d = detect.Detector()
    d._proc, d._model = ProcessorV5(found), (lambda **kw: ("raw", kw))
    return d


def test_owl_works_with_the_transformers_5_processor(monkeypatch):
    d = detector(monkeypatch)
    got = d.owl(Image.new("RGB", (160, 120)))
    assert got == {"label": "bird", "score": 0.6, "box": [0.25, 0.25, 0.75, 0.75]}
    (outputs, threshold, sizes), = d._proc.image_processor.calls
    assert outputs == ("raw", {"pixel_values": "px"})
    assert threshold == detect.MIN_SCORE and sizes == [(120, 160)]


def test_owl_finds_nothing(monkeypatch):
    assert detector(monkeypatch, found=False).owl(Image.new("RGB", (64, 64))) is None


def fake_transformers(seen):
    class Loader:
        @classmethod
        def from_pretrained(cls, model_id, **kw):
            seen.append((cls.__name__, model_id, kw))
            obj = cls()
            obj.config = types.SimpleNamespace(_commit_hash="abc123")
            obj.eval = lambda: obj
            return obj

    tf = types.ModuleType("transformers")
    tf.OwlViTProcessor = type("OwlViTProcessor", (Loader,), {})
    tf.OwlViTForObjectDetection = type("OwlViTForObjectDetection", (Loader,), {})
    return tf


def test_owl_model_revision_can_be_pinned(monkeypatch):
    seen = []
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers(seen))
    monkeypatch.setenv("UNSUB_OWL_REVISION", "0123abcd")
    detect.Detector()._load()
    assert [kw for _, _, kw in seen] == [{"revision": "0123abcd"}] * 2


def test_owl_model_is_unpinned_by_default(monkeypatch):
    seen = []
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers(seen))
    monkeypatch.delenv("UNSUB_OWL_REVISION", raising=False)
    detect.Detector()._load()
    assert [kw for _, _, kw in seen] == [{}, {}]


def test_bioclip_revision_loads_a_pinned_snapshot(monkeypatch):
    from wbs import embed
    calls = []
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = lambda repo, revision: calls.append((repo, revision)) or "/cache/bioclip@" + revision
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.delenv("UNSUB_BIOCLIP_REVISION", raising=False)
    assert embed.model_source() == (embed.HF_ID, "") and not calls
    monkeypatch.setenv("UNSUB_BIOCLIP_REVISION", "feed42")
    assert embed.model_source() == ("local-dir:/cache/bioclip@feed42", "feed42")
    assert calls == [("imageomics/bioclip-2", "feed42")]
