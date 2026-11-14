"""Count-only labels: a visit counts (species, how many, eBird) without its frames becoming training data."""
from datetime import date, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from test_mixed import mixed_visit
from test_train import CENTRES, DIM, RNG, FakeEmbedder
from wbs import main
from wbs.train import build_dataset

for _sp in ("Pine Siskin", "Common Redpoll"):
    CENTRES.setdefault(_sp, RNG.normal(size=DIM))


def teardown_module():
    with main.db.tx() as c:
        c.execute("DELETE FROM visits WHERE trace_id LIKE 'co%'")
        c.execute("DELETE FROM labels WHERE trace_id LIKE 'co%'")


def test_count_only_label_is_saved_and_can_skip_frames():
    frames, _ = mixed_visit("coapi", "Blue Jay", "Squirrel", n_main=2, n_other=0)
    c = TestClient(main.app)
    url = "/api/visits/coapi/label"
    # A training label still needs a frame; a count-only one doesn't (the bird may be hidden in every frame).
    assert c.post(url, json={"species": "Blue Jay", "frame_ids": []}).status_code == 400
    r = c.post(url, json={"species": "Blue Jay", "frame_ids": [], "count": 2, "train": False}).json()
    assert r["ok"] and r["train"] is False
    lab = c.get("/api/visits/coapi").json()["label"]
    assert lab["train"] == 0 and lab["count"] == 2
    # Turning it back into training data with frames ticked.
    assert c.post(url, json={"species": "Blue Jay", "frame_ids": frames}).json()["train"] is True
    assert c.get("/api/visits/coapi").json()["label"]["train"] == 1
    # The batch (Confirm all) carries it too.
    r = c.post("/api/labels/batch", json=[{"trace_id": "coapi", "species": "Blue Jay", "frame_ids": frames,
                                           "train": False}]).json()
    assert r["saved"] == 1 and r["results"][0]["train"] is False


def test_count_only_visit_counts_but_never_trains():
    when = datetime(2026, 2, 7, 9, 0)
    ids, _ = mixed_visit("cocount", "Pine Siskin", "Squirrel", n_main=3, n_other=0, ts=when.timestamp())
    main.db.set_label("cocount", "Pine Siskin", ids, 3, "confirmed", train=False)
    trained, _ = mixed_visit("cotrain", "Pine Siskin", "Squirrel", n_main=2, n_other=0, ts=when.timestamp() + 60)
    main.db.set_label("cotrain", "Pine Siskin", trained, None, "confirmed")

    main.embed_worker.embedder = FakeEmbedder()
    ds = build_dataset(main.db, main.embed_worker)
    assert "cocount" not in set(ds["groups"]) and "cotrain" in set(ds["groups"])

    c = TestClient(main.app)
    fw = c.get(f"/api/feederwatch?start={date(2026, 2, 7).isoformat()}").json()
    siskin = next(s for s in fw["species"] if s["species"] == "Pine Siskin")
    assert siskin["max"] == 3 and siskin["visits"] == 2         # the count-only visit is counted, with its number

    model = c.get("/api/model").json()
    assert model["visits_per_species"].get("Pine Siskin") == 1   # only the training visit
    stats = c.get("/api/stats").json()
    assert stats["count_only_visits"] >= 1
    row = next(s for s in stats["by_species"] if s["species"] == "Pine Siskin")
    assert row["visits"] == 2 and row["frames"] == 2 and row["count_only"] == 1


def test_exclude_still_drops_the_visit_from_counts():
    when = datetime(2026, 2, 14, 9, 0)
    ids, _ = mixed_visit("coexcl", "Common Redpoll", "Squirrel", n_main=1, n_other=0, ts=when.timestamp())
    main.db.set_label("coexcl", "Common Redpoll", ids, None, "confirmed", train=False)
    c = TestClient(main.app)
    start = date(2026, 2, 14).isoformat()
    assert any(s["species"] == "Common Redpoll" for s in c.get(f"/api/feederwatch?start={start}").json()["species"])
    c.post("/api/visits/coexcl/exclude", json={"excluded": True})
    assert not any(s["species"] == "Common Redpoll" for s in c.get(f"/api/feederwatch?start={start}").json()["species"])


def test_review_page_offers_count_only():
    js = (Path(main.__file__).parent / "static" / "app.js").read_text()
    assert 'class="countonly"' in js and "train: v._train" in js
