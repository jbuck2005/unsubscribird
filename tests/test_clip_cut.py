import subprocess

from fastapi.testclient import TestClient

from wbs import frames, main
from wbs.config import settings


def make_clip(path, seconds):
    """Like the camera: 10 fps, a keyframe every 2 s, AAC audio."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size=160x90:rate=10:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:v", "libx264", "-g", "20", "-keyint_min", "20",
                    "-sc_threshold", "0", "-c:a", "aac", "-shortest", str(path)], check=True)


def test_cut_at_the_two_second_keyframe_without_reencoding(tmp_path):
    clip = tmp_path / "a" / "clip.mp4"
    make_clip(clip, 8)
    assert frames.keyframes(clip)[:3] == [0.0, 2.0, 4.0]
    before = clip.stat().st_size
    assert frames.trim_start(clip, 2) == 2.0
    assert abs(frames.probe(clip)[0] - 6) < 0.3 and clip.stat().st_size < before
    first = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
                            "-show_entries", "frame=key_frame", "-of", "csv=p=0", str(clip)],
                           capture_output=True, text=True, check=True).stdout.split()[0]
    assert first.startswith("1")                             # the first video frame is a keyframe (clean start)
    assert not (clip.parent / "clip.trim.part.mp4").exists()


def test_short_clips_and_off_are_left_alone(tmp_path):
    short = tmp_path / "s" / "clip.mp4"
    make_clip(short, 3)                                     # cutting 2 s would leave 1 s
    size = short.stat().st_size
    assert frames.trim_start(short, 2) == 0.0 and short.stat().st_size == size
    assert frames.trim_start(short, 0) == 0.0
    late = tmp_path / "l" / "clip.mp4"
    late.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=8",
                    "-c:v", "libx264", "-g", "40", "-keyint_min", "40", "-sc_threshold", "0", str(late)], check=True)
    assert frames.trim_start(late, 2) == 0.0                 # next keyframe at 4 s: not cut


def test_existing_clips_are_cut_once_and_frame_times_shift():
    rel = "visits/cuttest/clip.mp4"
    clip = settings.image_dir / rel
    make_clip(clip, 8)
    (clip.parent / "clip_view.mp4").write_bytes(b"old copy")
    main.db.upsert_visit({"trace_id": "cuttest", "serial": "cam", "timestamp": 1.0, "time": "x"})
    main.db.add_frame("cuttest", "clip", "visits/cuttest/f1.jpg", None, 5.0, 0.5, 10, 10)
    main.db.add_frame("cuttest", "clip", "visits/cuttest/f2.jpg", None, 1.0, 0.4, 10, 10)
    main.db.set_visit("cuttest", clip=rel)
    main.trim_existing_clips()
    import time
    for _ in range(100):
        if main.db.one("SELECT clip_cut FROM visits WHERE trace_id='cuttest'")["clip_cut"] is not None:
            break
        time.sleep(0.1)
    assert main.db.one("SELECT clip_cut FROM visits WHERE trace_id='cuttest'")["clip_cut"] == 2.0
    ts = sorted(r["t"] for r in main.db.q("SELECT t FROM frames WHERE trace_id='cuttest'"))
    assert ts == [0.0, 3.0]                                  # 1.0 -> 0 (clamped), 5.0 -> 3.0
    assert not (clip.parent / "clip_view.mp4").exists()
    r = TestClient(main.app).get("/clips/cuttest/20260101_000000_blue-jay.mp4")
    assert r.status_code == 200 and r.content == clip.read_bytes()
