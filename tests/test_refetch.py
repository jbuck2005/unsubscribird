import io
import subprocess
import time

from fastapi.testclient import TestClient

from wbs import collector as col
from wbs import main
from wbs.config import settings


def make_clip(path, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=10:duration={seconds}",
                    "-c:v", "libx264", "-g", "20", "-pix_fmt", "yuv420p", "-y", str(path)], check=True)
    return path.read_bytes()


class Response:
    def __init__(self, status, body=b""):
        self.status_code, self.raw = status, io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))} if body else {}

    def close(self):
        pass


class Http:
    def __init__(self, response):
        self.response = response

    def get(self, url, **kw):
        return self.response


def visit_with_clip(trace, tmp_path, seconds=4, label=False):
    ts = time.time() - 3600
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": ts, "time": "x",
                          "clip_url": f"/local/vicohome/{trace}.mp4"})
    d = col.visit_dir(settings, trace, ts)
    d.mkdir(parents=True, exist_ok=True)
    data = make_clip(d / "clip.mp4", seconds)
    fid = main.db.add_frame(trace, "clip", col.rel(settings, d / "f0010.jpg"), None, 1.0, 0.5, 320, 180)
    main.db.set_visit(trace, clip=col.rel(settings, d / "clip.mp4"), clip_bytes=len(data), clip_cut=0.0,
                      status="prelabelled")
    if label:
        main.db.set_label(trace, "Blue Jay", [fid], None, "confirmed")
    return main.db.one("SELECT * FROM visits WHERE trace_id=?", trace), fid


def collector_with(response):
    c = col.Collector(settings, main.db)
    c.http = Http(response)
    return c


def test_a_clip_that_grew_is_fetched_again_with_new_frames(tmp_path):
    v, old = visit_with_clip("refetch1", tmp_path)
    longer = make_clip(tmp_path / "long.mp4", 12)
    assert collector_with(Response(200, longer)).refresh_clip(v) == "grew"
    after = main.db.one("SELECT * FROM visits WHERE trace_id='refetch1'")
    assert after["clip_bytes"] == len(longer) and after["clip_cut"] > 0
    frames = main.db.q("SELECT id, rejected FROM frames WHERE trace_id='refetch1'")
    assert {f["id"]: f["rejected"] for f in frames}[old] == 1                  # old frame kept, not used
    assert sum(not f["rejected"] for f in frames) >= 1                          # new frames from the long clip


def test_a_labelled_visit_keeps_its_frames(tmp_path):
    v, fid = visit_with_clip("refetch2", tmp_path, label=True)
    assert collector_with(Response(200, make_clip(tmp_path / "long2.mp4", 12))).refresh_clip(v) == "grew"
    assert main.db.one("SELECT rejected FROM frames WHERE id=?", fid)["rejected"] == 0
    assert main.db.one("SELECT species FROM labels WHERE trace_id='refetch2'")["species"] == "Blue Jay"


def test_same_size_or_gone_leaves_the_clip_alone(tmp_path):
    v, _ = visit_with_clip("refetch3", tmp_path)
    same = (settings.image_dir / v["clip"]).read_bytes()
    assert collector_with(Response(200, same)).refresh_clip(v) == "same"
    assert collector_with(Response(404)).refresh_clip(v) == "gone"
    assert main.db.one("SELECT clip_bytes FROM visits WHERE trace_id='refetch3'")["clip_bytes"] == len(same)


def test_fetch_clips_again_from_the_status_page(monkeypatch):
    calls = []
    monkeypatch.setattr(main.collector, "refetch_recent", lambda hours: calls.append(hours) or {"checked": 0})
    c = TestClient(main.app)
    assert c.post("/api/clips/refetch", json={"hours": 0}).status_code == 400
    assert c.post("/api/clips/refetch", json={"hours": 2}).json()["ok"]
    for _ in range(50):
        if not c.get("/api/clips/refetch").json()["running"]:
            break
        time.sleep(0.05)
    assert calls == [2] and c.get("/api/clips/refetch").json()["result"] == {"checked": 0}
    assert c.get("/admin/status").status_code == 200
