"""Mixed visits: per-frame species on a confirmed label (a squirrel frame in a chickadee visit)."""
import json
import time

import numpy as np
from fastapi.testclient import TestClient

from test_train import CENTRES, DIM, RNG, FakeEmbedder, add_visit, unit
from wbs import main
from wbs.embed import EMBEDDER, to_blob
from wbs.recognition import Recognizer
from wbs.train import Trainer, build_dataset, visit_labels, visits_per_class
from wbs.config import settings

CENTRES.setdefault("Squirrel", RNG.normal(size=DIM))


def teardown_module():
    with main.db.tx() as c:
        c.execute("DELETE FROM visits WHERE trace_id LIKE 'mx%'")
        c.execute("DELETE FROM labels")
        c.execute("DELETE FROM models")


def mixed_visit(trace, main_species, other, n_main=3, n_other=1, ts=None):
    """A visit whose last n_other frames show `other`; returns (main frame ids, other frame ids)."""
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": ts or time.time(), "time": "t"})
    ids = []
    for k, sp in enumerate([main_species] * n_main + [other] * n_other):
        p = settings.image_dir / "visits" / "mx" / trace / f"f{k}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"jpg")
        fid = main.db.add_frame(trace, "clip", str(p.relative_to(settings.image_dir)), None, float(k), 0.9 - k / 10,
                                2304, 1296)
        views = unit(CENTRES[sp] + RNG.normal(scale=0.35, size=(4, DIM)))
        with main.db.tx() as c:
            c.execute("INSERT INTO embeddings(frame_id, embedder, views, dim, data, created) VALUES (?,?,?,?,?,?)",
                      (fid, EMBEDDER, 4, DIM, to_blob(views), time.time()))
        ids.append(fid)
    main.db.set_visit(trace, status="prelabelled", clip=f"visits/mx/{trace}/clip.mp4")
    return ids[:n_main], ids[n_main:]


def test_label_api_validates_and_stores_frame_species():
    mine, other = mixed_visit("mxapi", "Black-capped Chickadee", "Squirrel", n_main=2, n_other=2)
    c = TestClient(main.app)
    url = "/api/visits/mxapi/label"
    body = {"species": "Black-capped Chickadee", "frame_ids": mine + other[:1]}
    assert c.post(url, json={**body, "frame_species": {str(other[0]): "Dragon"}}).status_code == 400
    assert c.post(url, json={**body, "frame_species": {str(f): "Squirrel" for f in body["frame_ids"]}}).status_code == 400
    r = c.post(url, json={**body, "frame_species": {str(other[0]): "squirrel",          # canonical spelling
                                                    str(other[1]): "Squirrel",          # unticked: ignored
                                                    str(mine[0]): "Black-capped Chickadee"}}).json()   # same: dropped
    assert r["frame_species"] == {str(other[0]): "Squirrel"} and r["also"] == ["Squirrel"]
    lab = c.get("/api/visits/mxapi").json()["label"]
    assert lab["frame_species"] == {str(other[0]): "Squirrel"} and lab["also"] == ["Squirrel"]
    r = c.post(url, json={**body, "frame_species": {str(other[0]): "Empty"}}).json()      # an empty frame: no also
    assert r["also"] == [] and c.get("/api/visits/mxapi").json()["label"]["frame_species"] == {str(other[0]): "Empty"}
    c.post(url, json=body)                                                                 # plain label clears them
    lab = main.db.one("SELECT frame_species, also FROM labels WHERE trace_id='mxapi'")
    assert lab["frame_species"] is None and lab["also"] is None


def test_frame_species_follow_a_swapped_frame():
    mine, other = mixed_visit("mxswap", "Blue Jay", "Squirrel")
    main.db.set_label("mxswap", "Blue Jay", mine + other, None, "confirmed", {other[0]: "Squirrel"})
    new = main.db.add_frame("mxswap", "clip", "visits/mx/mxswap/new.jpg", None, 9.0, 0.5, 10, 10)
    ids = [new if i == other[0] else i for i in mine + other]
    fs = json.loads(main.db.one("SELECT frame_species FROM labels WHERE trace_id='mxswap'")["frame_species"])
    fs[str(new)] = fs.pop(str(other[0]))
    main.db.set_label_frames("mxswap", ids, fs)
    lab = main.db.one("SELECT * FROM labels WHERE trace_id='mxswap'")
    assert json.loads(lab["frame_species"]) == {str(new): "Squirrel"} and json.loads(lab["also"]) == ["Squirrel"]
    main.db.set_label_frames("mxswap", mine, fs, touch=False)                              # frame dropped: species too
    lab = main.db.one("SELECT * FROM labels WHERE trace_id='mxswap'")
    assert lab["frame_species"] is None and lab["also"] is None


def test_units():
    y = np.array(["A", "A", "S", "A", "S", "B"])
    g = np.array(["v1", "v1", "v1", "v2", "v2", "v3"])
    assert visits_per_class(y, g) == {"A": 2, "S": 2, "B": 1}
    main_ = np.array(["A", "A", "A", "A", "A", "B"])
    assert list(visit_labels(y, main_, g, ["A", "S", "B"])) == list(main_)
    assert list(visit_labels(y[:5], main_[:5], g[:5], ["S"])) == ["S"] * 5     # main untrained: its frames' species


def test_training_learns_each_frame_as_its_own_species(tmp_path):
    with main.db.tx() as c:
        c.execute("DELETE FROM labels")
        c.execute("DELETE FROM models")
    main.embed_worker.embedder = FakeEmbedder()
    for i in range(5):
        add_visit(f"mxj{i}", "Blue Jay")
        add_visit(f"mxc{i}", "Black-capped Chickadee")
        add_visit(f"mxe{i}", "Empty")
    for i in range(3):          # squirrels only ever show up next to a chickadee
        mine, other = mixed_visit(f"mxm{i}", "Black-capped Chickadee", "Squirrel")
        main.db.set_label(f"mxm{i}", "Black-capped Chickadee", mine + other, None, "confirmed", {other[0]: "Squirrel"})
    ds = build_dataset(main.db, main.embed_worker)
    mixed = ds["groups"] == "mxm0"
    assert sorted(ds["y"][mixed]) == ["Black-capped Chickadee"] * 3 + ["Squirrel"]
    assert set(ds["main"][mixed]) == {"Black-capped Chickadee"}
    out = Trainer(main.db, main.embed_worker, tmp_path / "models").train()
    m = main.db.one("SELECT * FROM models WHERE id=?", out["model_id"])
    metrics = json.loads(m["metrics"])
    assert "Squirrel" in json.loads(m["classes"]) and metrics["visits"] == 18
    assert metrics["visit_accuracy"] >= 0.9     # mixed visits are scored by their main label (Chickadee)
    checks = {r["trace_id"]: r["label"] for r in main.db.q("SELECT * FROM label_checks WHERE model_id=?", m["id"])}
    assert checks["mxm0"] == "Black-capped Chickadee"


class Sink:
    def __init__(self):
        self.msgs = []

    def __call__(self, topic, payload, retain):
        self.msgs.append((topic, payload))


def test_ha_today_gallery_and_kids_page_count_the_second_species():
    now = time.time()
    mine, other = mixed_visit("mxha", "Blue Jay", "Squirrel", ts=now - 120)
    main.db.set_label("mxha", "Blue Jay", mine + other, None, "confirmed", {other[0]: "Squirrel"})
    jay2, _ = mixed_visit("mxha2", "Blue Jay", "Blue Jay", n_other=0, ts=now - 60)
    main.db.set_label("mxha2", "Blue Jay", jay2, None, "confirmed")
    rec = Recognizer(settings, main.db, Sink(), canonical=lambda n: n)
    for t in ("mxha", "mxha2"):
        main.db.set_visit(t, rec_species="Blue Jay", rec_source="confirmed", rec_conf=1.0, rec_at=now)
    today = rec.today_summary()
    assert today["by_species"]["Blue Jay"] >= 2 and today["other_animals"] >= 1
    sight = [s for s in today["sightings"] if s["trace_id"] == "mxha"]
    assert sorted(s["species"] for s in sight) == ["Blue Jay", "Squirrel"]
    assert rec.best_frame("mxha", "Squirrel")["id"] == other[0]           # its own frame, not the jay's
    assert rec.best_frame("mxha", "Blue Jay")["id"] in mine
    c = TestClient(main.app)
    day = c.get("/api/public/day").json()
    tile = next(v for v in day["visits"] if v["trace_id"] == "mxha")
    assert tile["species"] == "Blue Jay" and tile["also"] == ["Squirrel"] and day["counts"]["Squirrel"] >= 1
    assert tile["posters"]["Squirrel"] != tile["posters"]["Blue Jay"]
    sq = c.get("/api/public/day?species=Squirrel").json()["visits"]
    got = {v["trace_id"]: v for v in sq}
    assert "mxha" in got and "mxha2" not in got and got["mxha"]["species"] == "Squirrel" and got["mxha"]["also"] == ["Blue Jay"]
    assert got["mxha"]["poster"] == tile["posters"]["Squirrel"]
    g = c.get("/api/gallery?species=Squirrel").json()
    assert "mxha" in [v["trace_id"] for v in g["visits"]] and g["counts"]["Squirrel"] >= 1


def test_also_seen_names_a_species_without_its_own_frame():
    """Two birds in one frame: the second is 'also seen', shown everywhere `also` is, but never training data."""
    from test_api import seed_visit
    ids = seed_visit("trace0700", "Black-capped Chickadee")
    c = TestClient(main.app)
    r = c.post("/api/visits/trace0700/label", json={"species": "Black-capped Chickadee", "frame_ids": ids[:2],
               "also_seen": ["white-breasted nuthatch", "Black-capped Chickadee", "Empty"]}).json()
    assert r["also_seen"] == ["White-breasted Nuthatch"] and r["also"] == ["White-breasted Nuthatch"]
    lab = c.get("/api/visits/trace0700").json()["label"]
    assert lab["also_seen"] == ["White-breasted Nuthatch"] and lab["also"] == ["White-breasted Nuthatch"]
    assert lab["frame_species"] == {}                      # no frame was given the nuthatch
    main.db.set_label_frames("trace0700", ids[:1], {})     # a frame swap keeps it
    assert json.loads(main.db.one("SELECT also FROM labels WHERE trace_id='trace0700'")["also"]) == ["White-breasted Nuthatch"]
    bad = c.post("/api/visits/trace0700/label", json={"species": "Black-capped Chickadee", "frame_ids": ids[:1],
                 "also_seen": ["Dodo"]})
    assert bad.status_code == 400 and "also seen" in bad.json()["detail"]
    r = c.post("/api/visits/trace0700/label", json={"species": "Black-capped Chickadee", "frame_ids": ids[:1]}).json()
    assert r["also"] == [] and r["also_seen"] == []         # saving without it removes it
