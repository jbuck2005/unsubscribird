from datetime import date, datetime, timedelta

from fastapi.testclient import TestClient

from wbs import main


def visit(trace, when, rec=None, label=None, count=None, vlm_counts=(), also=None):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 10, 10)
    if rec:
        main.db.set_visit(trace, rec_species=rec, rec_source="model", rec_conf=0.9, rec_at=1)
    for n in vlm_counts:
        main.db.add_suggestion(trace, fid, "vlm", "m", {"bird_present": True, "species": (label or rec).lower(),
                                                         "count": n, "confidence": 0.9}, "")
    if label:
        main.db.set_label(trace, label, [fid], count, "confirmed", None, also)


def test_feederwatch_counts_the_most_at_once_not_the_visits():
    d = date(2026, 1, 10)
    at = lambda day, h: datetime(2026, 1, 10 + day, h, 0)          # noqa: E731
    visit("fw1", at(0, 8), rec="Black-capped Chickadee")             # no count anywhere: one bird
    visit("fw2", at(0, 9), rec="Black-capped Chickadee", vlm_counts=(2, 3))   # LM Studio saw 3 in one frame
    visit("fw3", at(1, 14), label="Black-capped Chickadee", count=4)          # you typed 4: wins
    visit("fw4", at(1, 15), label="Blue Jay", also=["White-breasted Nuthatch"])
    visit("fw5", at(1, 16), label="Squirrel")                                 # not a bird
    visit("fw6", at(2, 9), rec="Blue Jay")                                    # the day after the count
    r = TestClient(main.app).get(f"/api/feederwatch?start={d.isoformat()}").json()
    got = {s["species"]: (s["max"], s["days"], s["visits"], s["source"]) for s in r["species"]}
    assert got == {"Black-capped Chickadee": (4, {"2026-01-10": 3, "2026-01-11": 4}, 3, "you"),
                   "Blue Jay": (1, {"2026-01-11": 1}, 1, "one bird"),
                   "White-breasted Nuthatch": (1, {"2026-01-11": 1}, 1, "one bird")}
    assert [(e["bird_visits"], e["am"], e["pm"]) for e in r["effort"]] == [(2, 2, 0), (2, 0, 2)]
    csv = TestClient(main.app).get(f"/api/feederwatch?start={d.isoformat()}&format=csv")
    assert csv.headers["content-disposition"].endswith('feederwatch_2026-01-10_2026-01-11.csv"')
    assert csv.text.splitlines()[1] == "Black-capped Chickadee,4,3,4,3,you"
    assert TestClient(main.app).get("/api/feederwatch?start=nope").status_code == 400
    assert TestClient(main.app).get("/admin/patterns").status_code == 200


def test_review_saves_how_many():
    from datetime import datetime as dt
    visit("fwc1", dt(2026, 1, 20, 9), rec="Blue Jay")
    fid = main.db.one("SELECT id FROM frames WHERE trace_id='fwc1'")["id"]
    c = TestClient(main.app)
    assert c.post("/api/visits/fwc1/label", json={"species": "Blue Jay", "frame_ids": [fid], "count": 0}).status_code == 400
    assert c.post("/api/visits/fwc1/label", json={"species": "Blue Jay", "frame_ids": [fid], "count": 3}).json()["ok"]
    assert c.get("/api/visits/fwc1").json()["label"]["count"] == 3
