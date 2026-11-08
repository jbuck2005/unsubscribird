import time
from dataclasses import replace

from fastapi.testclient import TestClient

from wbs import main, retention
from wbs.config import settings

DAY = 86400
IDS = []


def teardown_module():
    with main.db.tx() as c:
        for t in IDS:
            c.execute("DELETE FROM visits WHERE trace_id=?", (t,))


def visit(trace, age_days, species=None, label_age_days=None, excluded=0):
    """A visit with a clip.mp4 and one frame on disk, labelled `species` (None = not labelled)."""
    IDS.append(trace)
    ts = time.time() - age_days * DAY
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": ts, "time": "t", "bird": "x"})
    vdir = settings.image_dir / "visits" / "ret" / trace
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "clip.mp4").write_bytes(b"0" * 1000)
    (vdir / "f0000.jpg").write_bytes(b"jpg")
    rel = lambda p: str(p.relative_to(settings.image_dir))  # noqa: E731
    fid = main.db.add_frame(trace, "clip", rel(vdir / "f0000.jpg"), None, 0.0, 0.5, 10, 10)
    main.db.set_visit(trace, clip=rel(vdir / "clip.mp4"), status="prelabelled", excluded=excluded)
    if species:
        main.db.set_label(trace, species, [fid], None, "confirmed")
        when = time.time() - (age_days if label_age_days is None else label_age_days) * DAY
        with main.db.tx() as c:
            c.execute("UPDATE labels SET updated=? WHERE trace_id=?", (when, trace))
    return vdir


def gone(trace):
    v = main.db.one("SELECT clip, clip_removed FROM visits WHERE trace_id=?", trace)
    return v["clip"] is None and v["clip_removed"] is not None


def test_only_old_confirmed_empty_clips_go():
    s = replace(settings, empty_clip_days=14)
    old_empty = visit("ret-old-empty", 20, "Empty")
    cases = {
        "ret-new-empty": visit("ret-new-empty", 3, "Empty"),             # too young
        "ret-old-bird": visit("ret-old-bird", 20, "Blue Jay"),           # a bird: never
        "ret-old-unlabelled": visit("ret-old-unlabelled", 20),           # nobody confirmed it
        "ret-old-excluded": visit("ret-old-excluded", 20, "Empty", excluded=1),
        "ret-just-relabelled": visit("ret-just-relabelled", 20, "Empty", label_age_days=0.1),  # grace day
    }
    r = retention.remove_empty_clips(s, main.db)
    assert r["removed"] >= 1 and r["freed_bytes"] >= 1000
    assert gone("ret-old-empty") and not (old_empty / "clip.mp4").exists()
    assert (old_empty / "f0000.jpg").exists()                           # frames stay
    assert main.db.one("SELECT species FROM labels WHERE trace_id='ret-old-empty'")["species"] == "Empty"
    for trace, vdir in cases.items():
        assert not gone(trace) and (vdir / "clip.mp4").exists(), trace
    assert retention.remove_empty_clips(s, main.db)["removed"] == 0     # nothing left to do


def test_zero_days_keeps_everything():
    vdir = visit("ret-keep", 400, "Empty")
    assert retention.remove_empty_clips(replace(settings, empty_clip_days=0), main.db)["removed"] == 0
    assert (vdir / "clip.mp4").exists() and not gone("ret-keep")
    main.db.delete_label("ret-keep")                                     # out of the way of the next test


def test_daily_cap_and_odd_paths():
    s = replace(settings, empty_clip_days=14)
    a, b = visit("ret-cap-a", 30, "Empty"), visit("ret-cap-b", 31, "Empty")
    recent = main.db.one("SELECT COUNT(*) n FROM visits WHERE clip_removed > ?", time.time() - DAY)["n"]
    assert retention.remove_empty_clips(s, main.db, per_day=recent + 1)["removed"] == 1
    assert gone("ret-cap-b") and not gone("ret-cap-a")                  # oldest first, then the cap
    assert (a / "clip.mp4").exists() and not (b / "clip.mp4").exists()
    outside = visit("ret-odd", 30, "Empty")
    main.db.set_visit("ret-odd", clip="../../etc/clip.mp4")
    r = retention.remove_empty_clips(s, main.db, per_day=10_000)
    assert r["skipped"] >= 1 and not gone("ret-odd") and (outside / "clip.mp4").exists()


def test_status_and_setting():
    c = TestClient(main.app)
    st = c.get("/api/stats").json()["retention"]
    assert st["empty_clip_days"] == settings.empty_clip_days and st["clips_removed"] >= 1
    assert c.put("/api/settings", json={"empty_clip_days": -1}).status_code == 400
    assert c.put("/api/settings", json={"empty_clip_days": 30}).status_code == 200 and settings.empty_clip_days == 30
    assert c.put("/api/settings", json={"empty_clip_days": None}).status_code == 200 and settings.empty_clip_days == 14
