import time

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings


def seed_visit(trace="trace0001", species="Blue Jay"):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 100,
                          "time": "2026-11-05T07:17:06-05:00", "bird": "Unidentified"})
    p = settings.image_dir / "visits" / trace
    p.mkdir(parents=True, exist_ok=True)
    ids = []
    for n in range(3):
        f = p / f"f{n}.jpg"
        f.write_bytes(b"\xff\xd8fake\xff\xd9")
        ids.append(main.db.add_frame(trace, "clip", str(f.relative_to(settings.image_dir)), None, n, 1 - n / 10, 2304, 1296))
    main.db.add_suggestion(trace, ids[0], "vlm", "m", {"bird_present": True, "species": species.lower(), "confidence": 0.9}, "")
    main.db.add_suggestion(trace, ids[1], "vlm", "m", {"bird_present": True, "species": species, "confidence": 0.8}, "")
    main.db.add_suggestion(trace, ids[2], "vlm", "m", {"bird_present": False}, "")
    main.db.set_visit(trace, status="prelabelled")
    return ids


def client():
    # no lifespan: don't start MQTT / LM Studio threads in tests
    return TestClient(main.app)


def test_review_queue_and_confirm():
    ids = seed_visit()
    c = client()
    r = c.get("/api/visits?queue=review").json()
    v = next(x for x in r["visits"] if x["trace_id"] == "trace0001")
    assert v["consensus"]["species"] == "Blue Jay" and v["consensus"]["known"]  # case normalised
    assert c.post("/api/visits/trace0001/label", json={"species": "blue jay", "frame_ids": ids[:2]}).json() == \
        {"ok": True, "species": "Blue Jay", "source": "confirmed", "frame_species": {}, "also": []}
    assert all(x["trace_id"] != "trace0001" for x in c.get("/api/visits?queue=review").json()["visits"])
    lab = c.get("/api/visits?queue=labelled").json()["visits"][0]["label"]
    assert lab["species"] == "Blue Jay" and lab["frame_ids"] == ids[:2]
    st = c.get("/api/stats").json()
    assert st["labelled_visits"] == 1 and st["labelled_frames"] == 2 and st["vlm_agreement"] == 1.0


def test_correction_and_validation():
    ids = seed_visit("trace0002", "Blue Jay")
    c = client()
    assert c.post("/api/visits/trace0002/label", json={"species": "Dodo", "frame_ids": ids}).status_code == 400
    assert c.post("/api/visits/trace0002/label", json={"species": "Northern Cardinal", "frame_ids": []}).status_code == 400
    assert c.post("/api/visits/trace0002/label", json={"species": "Northern Cardinal", "frame_ids": [999999]}).status_code == 400
    r = c.post("/api/visits/trace0002/label", json={"species": "Northern Cardinal", "frame_ids": ids}).json()
    assert r["source"] == "corrected"
    assert c.delete("/api/visits/trace0002/label").json() == {"ok": True}


def test_species_add_and_pages():
    c = client()
    assert c.post("/api/species", json={"name": "Lapland Longspur", "scientific": "Calcarius lapponicus"}).json()["ok"]
    assert c.post("/api/species", json={"name": "lapland longspur"}).status_code == 409
    for page in ("/", "/dataset", "/status"):
        assert c.get(page).status_code == 200
    assert c.get("/api/visits?queue=nope").status_code == 400


def test_collector_handlers_attach_snapshot_and_recent():
    col = main.collector
    rec = {"trace_id": "trace0100", "timestamp": time.time() - 50, "time": "2026-11-05T08:00:00-05:00",
           "bird": "Unidentified", "camera_name": "Bird Cam"}
    col.on_image("cam9", b"\xff\xd8jpeg\xff\xd9")
    col.on_last("cam9", rec)
    v = main.db.one("SELECT * FROM visits WHERE trace_id='trace0100'")
    assert v["snapshot"] and (settings.image_dir / v["snapshot"]).read_bytes().startswith(b"\xff\xd8")
    col.on_today("cam9", {"recent": [{"trace_id": "trace0101", "time": "2026-11-05T08:05:00-05:00",
                                      "bird": "Blue Jay", "clip_url": "/local/vicohome/trace0101.mp4"}]})
    v2 = main.db.one("SELECT * FROM visits WHERE trace_id='trace0101'")
    assert v2["clip_url"] == "/local/vicohome/trace0101.mp4" and v2["status"] == "new"


def test_batch_confirm_mixed_results():
    a = seed_visit("trace0200", "Blue Jay")
    b = seed_visit("trace0201", "Blue Jay")
    r = client().post("/api/labels/batch", json=[
        {"trace_id": "trace0200", "species": "Blue Jay", "frame_ids": a},
        {"trace_id": "trace0201", "species": "empty", "frame_ids": b[2:]},
        {"trace_id": "trace0201x", "species": "Blue Jay", "frame_ids": [1]},
        {"trace_id": "trace0200", "species": "Dodo", "frame_ids": a},
    ]).json()
    assert (r["saved"], r["failed"]) == (2, 2)
    assert [x["ok"] for x in r["results"]] == [True, True, False, False]
    assert r["results"][1]["species"] == "Empty" and r["results"][1]["source"] == "corrected"
    assert "not found" in r["results"][2]["error"] and "species list" in r["results"][3]["error"]
    lab = main.db.one("SELECT species FROM labels WHERE trace_id='trace0200'")
    assert lab["species"] == "Blue Jay"  # the later bad item did not overwrite it


def test_gallery_day_and_species():
    from datetime import datetime, timedelta
    c = client()
    # Early today, not noon: before noon, noon is "the future" and would be the newest visit for other tests.
    noon = datetime.now().replace(hour=0, minute=2, second=0, microsecond=0)
    def mk(trace, when, rec, label=None):
        main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
        fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 10, 10)
        main.db.set_visit(trace, rec_species=rec, rec_source="model", rec_conf=0.9, rec_at=1)
        if label:
            main.db.set_label(trace, label, [fid], None, "corrected")
    mk("gal1", noon, "Blue Jay")
    mk("gal2", noon + timedelta(minutes=5), "Blue Jay", label="Black-capped Chickadee")   # your label wins
    mk("gal3", noon - timedelta(days=1), "Blue Jay")                                       # yesterday
    mk("gal4", noon, "Empty")
    day = noon.date().isoformat()
    g = c.get(f"/api/gallery?day={day}&species=Blue Jay").json()
    mine = [v for v in g["visits"] if v["trace_id"].startswith("gal")]      # other tests add visits today too
    assert [v["trace_id"] for v in mine] == ["gal1"] and mine[0]["confirmed"] is False
    assert g["counts"].get("Black-capped Chickadee", 0) >= 1 and "Empty" not in g["counts"]
    allv = [v["trace_id"] for v in c.get(f"/api/gallery?day={day}").json()["visits"] if v["trace_id"].startswith("gal")]
    assert "gal4" not in allv and allv.index("gal2") < allv.index("gal1")                 # newest first, no empties
    y = c.get(f"/api/gallery?day={(noon - timedelta(days=1)).date().isoformat()}&species=Blue Jay").json()
    assert [v["trace_id"] for v in y["visits"] if v["trace_id"].startswith("gal")] == ["gal3"]
    assert c.get("/api/gallery?day=nope").status_code == 400
    assert c.get("/gallery").status_code == 200


def test_clip_names_follow_the_detection():
    from datetime import datetime
    when = datetime(2026, 11, 5, 9, 17, 2)
    main.db.upsert_visit({"trace_id": "clipn1", "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    p = settings.image_dir / "visits" / "clipn1"
    p.mkdir(parents=True, exist_ok=True)
    (p / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42fake")
    fid = main.db.add_frame("clipn1", "clip", "visits/clipn1/f.jpg", None, 1.0, 0.5, 10, 10)
    main.db.set_visit("clipn1", clip="visits/clipn1/clip.mp4", status="prelabelled")
    c = client()
    assert c.get("/api/visits/clipn1").json()["clip_name"] == "20261105_091702_unidentified.mp4"
    main.db.set_visit("clipn1", rec_species="Cooper's Hawk", rec_source="model")
    assert c.get("/api/visits/clipn1").json()["clip_name"] == "20261105_091702_coopers-hawk.mp4"
    main.db.set_label("clipn1", "Black-capped Chickadee", [fid], None, "confirmed")       # your label wins
    v = c.get("/api/visits/clipn1").json()
    assert v["clip_name"] == "20261105_091702_black-capped-chickadee.mp4"
    r = c.get(v["clip_href"])
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert 'filename="20261105_091702_black-capped-chickadee.mp4"' in r.headers["content-disposition"]
    assert r.headers["content-disposition"].startswith("inline")
    assert c.get("/clips/nope/x.mp4").status_code == 404
