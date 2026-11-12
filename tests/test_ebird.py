from datetime import datetime

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings


def visit(trace, when, species, count=None, vlm=()):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 10, 10)
    main.db.set_visit(trace, rec_species=species, rec_source="model", rec_conf=0.9, rec_at=1)
    for n in vlm:
        main.db.add_suggestion(trace, fid, "vlm", "m", {"bird_present": True, "species": species, "count": n,
                                                         "confidence": 0.9}, "")
    if count:
        main.db.set_label(trace, species, [fid], count, "confirmed")


def test_ebird_record_format(monkeypatch):
    monkeypatch.setattr(settings, "ebird_location", 'Back "yard", feeder')
    monkeypatch.setattr(settings, "ebird_protocol", "stationary")
    at = lambda d, h, m=0: datetime(2025, 2, d, h, m)          # noqa: E731  (no other test uses Feb 2025)
    visit("eb1", at(14, 8, 5), "Black-capped Chickadee")         # nobody counted: X
    visit("eb2", at(14, 9), "Black-capped Chickadee", vlm=(2, 3))  # LM Studio saw 3 at once
    visit("eb3", at(14, 11, 30), "Blue Jay", count=2)             # you typed 2
    visit("eb4", at(14, 12), "Squirrel")                          # not a bird
    visit("eb5", at(15, 10), "Blue Jay")
    c = TestClient(main.app)
    r = c.get("/api/ebird?start=2025-02-14&end=2025-02-16").json()
    assert [x["day"] for x in r["checklists"]] == ["2025-02-14", "2025-02-15"]     # no birds on the 16th: no list
    feb14 = r["checklists"][0]
    assert (feb14["start"], feb14["minutes"]) == ("08:05", 206)
    assert [(s["species"], s["number"]) for s in feb14["species"]] == [("Black-capped Chickadee", 3), ("Blue Jay", 2)]
    lines = c.get("/api/ebird?start=2025-02-14&end=2025-02-15&format=csv").text.splitlines()
    assert len(lines) == 3 and not lines[0].startswith("Common Name")                # no header row
    cols = lines[0].split(",")
    assert len(cols) == 19 and '"' not in lines[0]
    assert cols[:4] == ["Black-capped Chickadee", "Poecile", "atricapillus", "3"]
    assert cols[5] == "Back yard feeder" and cols[8:10] == ["02/14/2025", "08:05"]
    assert cols[10:16] == ["ON", "CA", "Stationary", "1", "206", "Y"]
    assert lines[2].split(",")[3] == "X" and lines[2].split(",")[8] == "02/15/2025"      # uncounted Blue Jay
    monkeypatch.setattr(settings, "ebird_protocol", "incidental")
    cols = c.get("/api/ebird?start=2025-02-15&format=csv").text.split(",")
    assert cols[12:16] == ["Incidental", "1", "", "N"]
    assert c.get("/api/ebird?start=2025-02-15&end=2025-02-14").status_code == 400
