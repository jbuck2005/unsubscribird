from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings


def visit(trace, when, species, label=False, count=None, excluded=0):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    d = settings.image_dir / "visits" / trace
    d.mkdir(parents=True, exist_ok=True)
    (d / "clip.mp4").write_bytes(b"clip")
    fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 10, 10)
    main.db.set_visit(trace, clip=f"visits/{trace}/clip.mp4", rec_species=species, rec_source="model", rec_conf=0.9,
                      rec_at=1, excluded=excluded)
    if label:
        main.db.set_label(trace, species, [fid], count, "confirmed")
    return fid


def test_species_card_stats_come_from_public_visits():
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    sp = "Evening Grosbeak"                                       # no other test uses it
    visit("sc1", now - timedelta(days=2, hours=1), sp)
    visit("sc2", now - timedelta(days=1), sp, label=True, count=3)
    visit("sc3", now - timedelta(minutes=5) if now.hour else now, sp)
    visit("sc4", now - timedelta(days=3), sp, excluded=1)         # excluded: not public, not counted
    c = TestClient(main.app).get(f"/api/public/species-card?species={sp}").json()
    assert (c["today"], c["all_time"], c["most_at_once"]) == (1, 3, 3)
    assert c["streak"] == 3 and c["scientific"] == "Coccothraustes vespertinus"
    assert c["first_seen"] == (now - timedelta(days=2, hours=1)).timestamp()
    assert c["portrait"] == f"/api/public/portrait/sc2?species={sp.replace(' ', '%20')}"   # the one you labelled
    assert c["about"]["Wikipedia"].endswith("Coccothraustes_vespertinus") and c["rank"] >= 1
    assert TestClient(main.app).get("/api/public/species-card?species=Empty").status_code == 404
    assert TestClient(main.app).get("/api/public/species-card?species=Dodo").status_code == 404


def test_wrong_bird_flag_goes_to_review_until_labelled():
    when = datetime.now() - timedelta(hours=1)
    fid = visit("fl1", when, "Blue Jay")
    visit("fl2", when, "Uncertain")                                # not on the home page
    c = TestClient(main.app)
    assert c.post("/api/public/flag/fl2", json={}).status_code == 404
    assert c.post("/api/public/flag/fl1", json={"note": "  looks   like a\\n" + "jay " * 40}).json()["ok"]
    v = main.db.one("SELECT flagged, flag_note FROM visits WHERE trace_id='fl1'")
    assert v["flagged"] and len(v["flag_note"]) == 80 and "  " not in v["flag_note"]
    q = c.get("/api/visits?queue=flagged").json()
    assert q["total"] >= 1 and q["visits"][0]["trace_id"] == "fl1" and q["visits"][0]["flag_note"].startswith("looks like")
    c.post("/api/visits/fl1/label", json={"species": "Blue Jay", "frame_ids": [fid]})      # a person looked
    assert all(x["trace_id"] != "fl1" for x in c.get("/api/visits?queue=flagged").json()["visits"])
