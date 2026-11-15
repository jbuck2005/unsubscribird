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
