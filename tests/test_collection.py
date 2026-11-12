import os
from datetime import datetime

from fastapi.testclient import TestClient
from PIL import Image

from wbs import main
from wbs.config import settings


def visit(trace, when, species, label=False, also=None, conf=0.9):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    d = settings.image_dir / "visits" / trace
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 36), (200, 120, 40)).save(d / "f.jpg")
    (d / "clip.mp4").write_bytes(b"clip")
    fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 64, 36)
    main.db.set_visit(trace, clip=f"visits/{trace}/clip.mp4", rec_species=species, rec_source="model", rec_conf=conf, rec_at=1)
    if label:
        main.db.set_label(trace, species, [fid], None, "confirmed", None, also)


def test_collection_book_lists_found_birds_and_the_ones_to_find():
    c = TestClient(main.app)
    visit("col1", datetime(2024, 3, 2, 9), "Blue Jay", conf=0.8)
    visit("col2", datetime(2024, 3, 5, 9), "Blue Jay", label=True, also=["White-breasted Nuthatch"])
    visit("col3", datetime(2024, 4, 1, 9), "Squirrel")                 # not a bird
    visit("col4", datetime(2024, 4, 2, 9), "Uncertain")                # not public
    visit("col5", datetime(2023, 12, 31, 9), "Pine Grosbeak")          # last year
    r = c.get("/api/public/collection?year=2024").json()
    found = {b["species"]: b for b in r["found"]}
    assert list(found) == ["Blue Jay", "White-breasted Nuthatch"]       # in the order first seen
    jay = found["Blue Jay"]
    assert jay["visits"] == 2 and jay["first"] == datetime(2024, 3, 2, 9).timestamp()
    assert jay["portrait"] == "/api/public/portrait/col2?species=Blue%20Jay"   # the one you labelled
    assert "Pine Grosbeak" in r["to_find"] and "Blue Jay" not in r["to_find"] and "Squirrel" not in r["to_find"]
    assert "Unknown bird" not in r["to_find"] and r["first_year"] <= 2023
    img = c.get(jay["portrait"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert c.get("/api/public/portrait/col4?species=Uncertain").status_code == 404   # hidden visits stay hidden
    assert c.get("/api/public/collection?year=1").status_code == 400


def test_collection_is_public():
    os.environ["UNSUB_AUTH"] = "on"
    os.environ["UNSUB_ADMIN_PASSWORD"] = "hunter2-bird"
    try:
        c = TestClient(main.app, follow_redirects=False)
        assert c.get("/collection").status_code == 200 and c.get("/api/public/collection").status_code == 200
    finally:
        os.environ["UNSUB_AUTH"] = "off"
        os.environ.pop("UNSUB_ADMIN_PASSWORD", None)
