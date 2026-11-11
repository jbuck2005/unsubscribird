import json
import subprocess
import time

from fastapi.testclient import TestClient

from wbs import frames, main
from wbs.config import settings


def make_video(path, seconds=6):
    """A test clip: moving test pattern (so frames differ), 640x360."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=10:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(path)], check=True)


def test_replacement_time_avoids_used_moments(tmp_path):
    clip = tmp_path / "c.mp4"
    make_video(clip)
    used = [1.0, 2.0]
    t = frames.replacement_time(clip, used)
    assert t is not None and all(abs(t - u) >= 1.0 for u in used)
    every = [x / 2 for x in range(13)]          # every analysed moment already used
    assert frames.replacement_time(clip, every) is None


def test_replace_frame_endpoint(tmp_path):
    trace = "trace0300"
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 100,
                          "time": "2026-11-05T09:00:00-05:00", "bird": "Unidentified"})
    vdir = settings.image_dir / "visits" / trace
    clip = vdir / "clip.mp4"
    make_video(clip)
    rel = lambda p: str(p.relative_to(settings.image_dir))  # noqa: E731
    ids = []
    for t in (1.0, 3.0):
        full = vdir / f"f{int(t * 10):04d}.jpg"
        frames.cut(clip, t, full)
        ids.append(main.db.add_frame(trace, "clip", rel(full), rel(full), t, 0.5, 640, 360))
    main.db.set_visit(trace, clip=rel(clip), status="prelabelled")
    main.db.set_label(trace, "Blue Jay", ids, None, "confirmed")

    c = TestClient(main.app)
    r = c.post(f"/api/frames/{ids[0]}/replace").json()
    assert r["ok"] and r["suggestion"] is None          # LM Studio unreachable in tests: frame still added
    new = r["frame"]
    assert abs(new["t"] - 1.0) >= 1.0 and abs(new["t"] - 3.0) >= 1.0
    assert (settings.image_dir / new["path"]).exists() and (settings.image_dir / new["thumb"]).exists()

    v = c.get(f"/api/visits/{trace}").json()
    shown = [f["id"] for f in v["frames"]]
    assert ids[0] not in shown and new["id"] in shown   # the rejected frame is hidden
    assert v["label"]["frame_ids"] == [new["id"], ids[1]]  # the label follows the replacement

    assert c.post(f"/api/frames/{ids[0]}/replace").status_code == 404   # already rejected
    lab = json.loads(main.db.one("SELECT frame_ids FROM labels WHERE trace_id=?", trace)["frame_ids"])
    assert ids[0] not in lab


def test_replace_needs_a_clip():
    trace = "trace0301"
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time(), "time": "x"})
    p = settings.image_dir / "visits" / trace / "snapshot.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xd8x\xff\xd9")
    fid = main.db.add_frame(trace, "snapshot", str(p.relative_to(settings.image_dir)), None, None, None, None, None)
    r = TestClient(main.app).post(f"/api/frames/{fid}/replace")
    assert r.status_code == 409 and "no clip" in r.json()["detail"]


def test_quiet_clip_skips_lmstudio_and_suggests_empty():
    import json as _json
    from wbs.recognition import Recognizer
    trace = "trace0400"
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 100,
                          "time": "2026-11-05T12:00:00-05:00", "clip_url": "/local/vicohome/x.mp4"})
    v = main.db.one("SELECT * FROM visits WHERE trace_id=?", trace)
    clip = main.collector.s.image_dir / "visits" / "2026" / "11" / "05" / trace / "clip.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=10:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(clip)], check=True)
    from wbs import collector as col
    orig = col.visit_dir
    col.visit_dir = lambda s, t, ts: clip.parent          # use the clip we just made (no HTTP download)
    try:
        main.collector.fetch_clip(v)
    finally:
        col.visit_dir = orig
    v = main.db.one("SELECT * FROM visits WHERE trace_id=?", trace)
    assert v["quiet"] == 1 and v["status"] == "prelabelled" and v["activity"] < 0.025
    api = TestClient(main.app).get(f"/api/visits/{trace}").json()
    assert api["consensus"]["species"] == "Empty" and api["quiet"] == 1
    sent = []
    r = Recognizer(main.collector.s, main.db, lambda t, p, keep: sent.append((t, p)))
    assert r.decide_visit(trace)[0]["source"] == "motion"
    with main.db.tx() as c:
        c.execute("UPDATE visits SET rec_at=0 WHERE trace_id != ?", (trace,))
    r.run_once()
    assert _json.loads(next(p for t, p in sent if t == "unsubscribird/last_visit"))["species"] == "Empty"


def test_owlvit_overrules_nothing_moved_for_a_still_bird():
    """A bird that sits still barely changes the clip; OWL-ViT on the best frame stops it being called Empty."""
    from wbs import collector as col

    class FakeDetector:
        def __init__(self, result):
            self.result, self.calls = result, 0

        def owl(self, img):
            self.calls += 1
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    def run(trace, result):
        main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 100,
                              "time": "2026-11-05T12:00:00-05:00", "clip_url": "/local/vicohome/x.mp4"})
        clip = settings.image_dir / "visits" / "still" / trace / "clip.mp4"
        clip.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=10:duration=4",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(clip)], check=True)
        det, orig = FakeDetector(result), col.visit_dir
        main.collector.detector, col.visit_dir = det, (lambda s, t, ts: clip.parent)
        try:
            main.collector.fetch_clip(main.db.one("SELECT * FROM visits WHERE trace_id=?", trace))
        finally:
            main.collector.detector, col.visit_dir = None, orig
        motion = main.db.one("SELECT 1 FROM suggestions WHERE trace_id=? AND source='motion'", trace)
        return main.db.one("SELECT * FROM visits WHERE trace_id=?", trace), det.calls, motion is not None

    v, calls, motion = run("trace0410", {"label": "bird", "score": 0.72, "box": [0.3, 0.2, 0.6, 0.6]})
    assert calls == 1 and v["quiet"] == 0 and v["status"] == "frames" and not motion   # on to LM Studio
    v, _, motion = run("trace0411", {"label": "bird", "score": 0.2, "box": [0.3, 0.2, 0.6, 0.6]})
    assert v["quiet"] == 1 and v["status"] == "prelabelled" and motion                  # too unsure
    v, _, motion = run("trace0412", RuntimeError("model missing"))
    assert v["quiet"] == 1 and motion                                                   # no verdict: as before
