"""Runs the real models inside the built image (docker.yml): OWL-ViT detection and a BioCLIP 2 embedding on a
blank frame. Catches library upgrades that break the model calls, which the unit tests (with fakes) can't.
Not collected by pytest (no test_ prefix); needs the image's torch and ML requirements, and downloads the models."""
from PIL import Image

from wbs.detect import Detector
from wbs.embed import Embedder

img = Image.new("RGB", (640, 360), (120, 140, 90))
print("OWL-ViT:", Detector().owl(img))
e = Embedder(threads=2).embed_image(None, img=img)
assert e.ndim == 2 and e.shape[0] == 4, e.shape
print("BioCLIP 2 embedding:", e.shape)
