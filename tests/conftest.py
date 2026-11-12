import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
_tmp = tempfile.mkdtemp(prefix="wbs-test-")
os.environ.setdefault("UNSUB_DATA_DIR", f"{_tmp}/data")
os.environ.setdefault("UNSUB_IMAGE_DIR", f"{_tmp}/images")
os.environ.setdefault("UNSUB_HOST", "192.0.2.10")
os.environ.setdefault("UNSUB_MQTT_HOST", "127.0.0.1")
os.environ.setdefault("UNSUB_LMSTUDIO_URL", "http://127.0.0.1:9")
os.environ.setdefault("UNSUB_DETECT", "false")   # OWL-ViT would download a model; tests use fakes
os.environ.setdefault("UNSUB_AUTH", "off")   # test_auth.py switches it on
os.environ.setdefault("UNSUB_ALLOWED_HOSTS", "testserver")   # TestClient's host
