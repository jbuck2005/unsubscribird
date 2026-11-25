import time
from dataclasses import replace

from fastapi.testclient import TestClient

from wbs import main, retention, triage
from wbs.config import settings

DAY = 86400
IDS = []


def teardown_module():
    with main.db.tx() as c:
        for t in IDS:
            c.execute("DELETE FROM visits WHERE trace_id=?", (t,))
        c.execute("UPDATE visits SET triage=NULL, triaged=NULL")   # leave other tests' visits as they were


def visit(trace, ts=None, quiet=False, vlm=None, model=None, owl=False, flagged=False, activity=None):
    """An unconfirmed visit to review. vlm / model: (species, confidence); vlm species None = no bird seen."""
    IDS.append(trace)
    ts = ts or time.time() - 600
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": ts, "time": "t", "bird": "x"})
    vdir = settings.image_dir / "visits" / "tri" / trace
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "clip.mp4").write_bytes(b"0" * 1000)
    (vdir / "f0.jpg").write_bytes(b"jpg")
    rel = lambda p: str(p.relative_to(settings.image_dir))  # noqa: E731
    fid = main.db.add_frame(trace, "clip", rel(vdir / "f0.jpg"), None, 0.0, 0.5, 10, 10)
    if quiet:
        main.db.add_suggestion(trace, None, "motion", "frame-picker",
                               {"bird_present": False, "species": "Empty", "confidence": 0.9}, "")
    if vlm:
        main.db.add_suggestion(trace, fid, "vlm", "m", {"bird_present": vlm[0] is not None, "species": vlm[0],
                                                        "confidence": vlm[1]}, "")
    if model:
        main.db.add_suggestion(trace, None, "model", "v1", {"species": model[0], "confidence": model[1]}, "")
    if owl:
        with main.db.tx() as c:
            c.execute("""INSERT INTO detections(frame_id, source, label, score, x1, y1, x2, y2, created)
                         VALUES (?, 'owlvit', 'bird', 0.2, 0.1, 0.1, 0.2, 0.2, ?)""", (fid, time.time()))
    main.db.set_visit(trace, clip=rel(vdir / "clip.mp4"), status="prelabelled", quiet=int(quiet),
                      activity=activity, flagged=time.time() if flagged else None)
    return trace


def row(trace):
    return main.db.one("SELECT * FROM visits WHERE trace_id=?", trace)


def ids(c, queue):
    return {v["trace_id"] for v in c.get(f"/api/visits?queue={queue}&limit=100").json()["visits"]}


def test_only_sure_empties_count():
    sure = {
        "tri-quiet": visit("tri-quiet", quiet=True),
        "tri-all-agree": visit("tri-all-agree", vlm=(None, 0.9), model=("Empty", 0.95)),
    }
    doubtful = {
        "tri-model-bird": visit("tri-model-bird", vlm=(None, 0.9), model=("Blue Jay", 0.97)),
        "tri-model-unsure": visit("tri-model-unsure", vlm=(None, 0.9), model=("Empty", 0.8)),
        "tri-vlm-unsure": visit("tri-vlm-unsure", vlm=(None, 0.5), model=("Empty", 0.99)),
        "tri-vlm-bird": visit("tri-vlm-bird", vlm=("Blue Jay", 0.9), model=("Empty", 0.99)),
        "tri-boxed": visit("tri-boxed", quiet=True, owl=True),
        "tri-flagged": visit("tri-flagged", quiet=True, flagged=True),
    }
    for t in sure:
        assert triage.sure_empty(main.db, row(t), has_model=True), t
    for t in doubtful:
        assert not triage.sure_empty(main.db, row(t), has_model=True), t
    # Something moved and the model hasn't answered: wait for it, unless there is no model at all.
    visit("tri-no-model-yet", vlm=(None, 0.9))
    assert not triage.sure_empty(main.db, row("tri-no-model-yet"), has_model=True)
    assert triage.sure_empty(main.db, row("tri-no-model-yet"), has_model=False)


def test_filed_visits_leave_review_and_can_come_back():
    c = TestClient(main.app)
    visit("tri-q-filed", quiet=True)
    visit("tri-q-bird", vlm=("Blue Jay", 0.9), model=("Blue Jay", 0.99))
    assert {"tri-q-filed", "tri-q-bird"} <= ids(c, "review")
    triage.file_sure_empties(main.db)
    assert row("tri-q-filed")["triage"] == "filed" and row("tri-q-bird")["triage"] is None
    assert "tri-q-filed" not in ids(c, "review") and "tri-q-bird" in ids(c, "review")
    assert "tri-q-filed" in ids(c, "filed")
    v = c.get("/api/visits/tri-q-filed").json()
    assert v["triage"] == "filed" and v["best"]["species"] == "Empty"     # still counts as Empty

    assert c.post("/api/visits/tri-q-filed/unfile").status_code == 200
    assert c.post("/api/visits/tri-q-filed/unfile").status_code == 404     # not filed any more
    triage.file_sure_empties(main.db)
    assert row("tri-q-filed")["triage"] == "kept"                           # a person sent it back: never refiled
    assert "tri-q-filed" in ids(c, "review") and "tri-q-filed" not in ids(c, "filed")


def test_confirming_a_filed_visit_takes_it_out_of_filed():
    c = TestClient(main.app)
    visit("tri-confirm", quiet=True)
    triage.file_sure_empties(main.db)
    fid = c.get("/api/visits/tri-confirm").json()["frames"][0]["id"]
    assert c.post("/api/visits/tri-confirm/label", json={"species": "Empty", "frame_ids": [fid]}).status_code == 200
    assert "tri-confirm" not in ids(c, "filed")


def test_daily_sample_spreads_over_the_day(monkeypatch):
    now = time.time()
    yday = triage.day_start(triage.day_start(now) - DAY / 2)
    at = lambda h: yday + h * 3600 + 60  # noqa: E731
    # 07:00 block twice (the calmer clip and the one that moved more), 13:00 once, 16:00 once.
    visit("tri-s-7a", ts=at(7), quiet=True, activity=0.005)
    visit("tri-s-7b", ts=at(7.5), quiet=True, activity=0.02)
    visit("tri-s-13", ts=at(13), quiet=True, activity=0.01)
    visit("tri-s-16", ts=at(16), quiet=True, activity=0.01)
    visit("tri-s-today", quiet=True)                         # today's visits wait for tomorrow's sample
    triage.file_sure_empties(main.db)
    # 13:00 and 16:00 already have confirmed Empty visits this fortnight; 06:00-09:00 has none.
    for i, h in enumerate((13, 13, 16)):
        t = visit(f"tri-s-label{i}", ts=at(h) - 5 * DAY, quiet=True)
        main.db.set_label(t, "Empty", [], None, "confirmed", train=False)
    cover = triage.coverage(main.db, now)
    assert cover[triage.block(at(13))] >= 2 and cover[triage.block(at(16))] >= 1
    # Other tests label Empty visits at today's time of day: count only this test's labels.
    monkeypatch.setattr(triage, "coverage", lambda db, now: {triage.block(at(13)): 2, triage.block(at(16)): 1})
    assert triage.sample_day(main.db, 2, now) == 2
    picked = {r["trace_id"] for r in main.db.q("SELECT trace_id FROM visits WHERE triage='sample'")}
    assert picked == {"tri-s-7b", "tri-s-16"}       # least covered block first, then the clip that moved most
    assert triage.sample_day(main.db, 2, now) == 0  # once a day
    c = TestClient(main.app)
    assert picked <= ids(c, "review") and not picked & ids(c, "filed")
    assert c.get("/api/visits/tri-s-7b").json()["triage"] == "sample"


def test_off_sends_filed_visits_back():
    visit("tri-off", quiet=True)
    triage.file_sure_empties(main.db)
    assert row("tri-off")["triage"] == "filed"
    r = triage.run_pass(replace(settings, empty_auto_file=False), main.db)
    assert r["unfiled"] >= 1 and row("tri-off")["triage"] is None
    triage.run_pass(replace(settings, empty_auto_file=True, empty_review_per_day=0), main.db)
    assert row("tri-off")["triage"] == "filed"


def test_retention_deletes_old_filed_clips_only():
    old = time.time() - 20 * DAY
    visit("tri-r-filed", ts=old, quiet=True)
    visit("tri-r-kept", ts=old, quiet=True)
    triage.file_sure_empties(main.db)
    with main.db.tx() as c:
        c.execute("UPDATE visits SET triaged=? WHERE trace_id IN ('tri-r-filed', 'tri-r-kept')", (time.time() - 2 * DAY,))
        c.execute("UPDATE visits SET triage='kept' WHERE trace_id='tri-r-kept'")
    visit("tri-r-fresh", ts=old, quiet=True)
    triage.file_sure_empties(main.db)                    # filed just now: a day's grace before its clip goes
    retention.remove_empty_clips(replace(settings, empty_clip_days=14), main.db, per_day=10_000)
    assert row("tri-r-filed")["clip"] is None and row("tri-r-filed")["clip_removed"] is not None
    assert row("tri-r-kept")["clip"] is not None and row("tri-r-fresh")["clip"] is not None


def test_settings_and_stats():
    c = TestClient(main.app)
    assert c.put("/api/settings", json={"empty_review_per_day": -1}).status_code == 400
    assert c.put("/api/settings", json={"empty_review_per_day": 5}).status_code == 200
    assert settings.empty_review_per_day == 5
    assert c.put("/api/settings", json={"empty_review_per_day": None}).status_code == 200
    assert settings.empty_review_per_day == 2
    assert c.put("/api/settings", json={"empty_auto_file": "yes"}).status_code == 400
    st = c.get("/api/stats").json()["triage"]
    assert st["on"] is True and st["per_day"] == 2 and st["filed"] >= 1
    assert c.get("/api/visits?queue=filed&limit=0").json()["total"] == st["filed"]
