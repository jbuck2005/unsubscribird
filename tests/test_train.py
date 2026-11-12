import json
import time

import numpy as np
from fastapi.testclient import TestClient

from wbs import main
from wbs.embed import EMBEDDER, make_views, species_text, to_blob, zero_shot
from wbs.train import Trainer, build_dataset, metrics_from

DIM = 32
RNG = np.random.default_rng(1)
CENTRES = {n: RNG.normal(size=DIM) for n in ("Blue Jay", "Black-capped Chickadee", "Empty", "Northern Cardinal")}


def unit(x):
    return (x / np.linalg.norm(x, axis=-1, keepdims=True)).astype(np.float32)


class FakeEmbedder:
    """Text embedding = class centre; images are generated near the centre of their species."""

    def text_embeddings(self, species):
        names = [n for n, s, k in species if species_text(n, s, k)]
        return names, unit(np.array([CENTRES.get(n, RNG.normal(size=DIM)) for n in names]))


def add_visit(trace, species, n_frames=3, label=True, noise=0.35):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time(), "time": "2026-11-05T10:00:00-05:00"})
    ids = []
    for k in range(n_frames):
        fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f{k}.jpg", None, float(k), 0.5, 2304, 1296)
        views = unit(CENTRES[species] + RNG.normal(scale=noise, size=(4, DIM)))
        views[0] = unit(CENTRES[species] + RNG.normal(scale=noise * 2, size=DIM))   # full view: noisier
        with main.db.tx() as c:
            c.execute("INSERT INTO embeddings(frame_id, embedder, views, dim, data, created) VALUES (?,?,?,?,?,?)",
                      (fid, EMBEDDER, 4, DIM, to_blob(views), time.time()))
        ids.append(fid)
    main.db.set_visit(trace, status="prelabelled")
    main.db.add_suggestion(trace, ids[0], "vlm", "m", {"bird_present": species != "Empty", "species": species,
                                                        "confidence": 0.9}, "")
    if label:
        main.db.set_label(trace, species, ids, None, "confirmed")
    return ids


def test_make_views_shapes():
    from PIL import Image
    v = make_views(Image.new("RGB", (2304, 1296)))
    assert [x.size for x in v] == [(2304, 2304), (1296, 1296), (1296, 1296), (1296, 1296)]


def test_zero_shot_picks_the_animal_view():
    names = ["Blue Jay", "Empty"]
    text = unit(np.array([CENTRES["Blue Jay"], CENTRES["Empty"]]))
    views = unit(np.array([CENTRES["Empty"], CENTRES["Empty"], CENTRES["Blue Jay"], CENTRES["Empty"]]))
    z = zero_shot(views, names, text, {"Empty"})
    assert z["view"] == 2 and z["species"] == "Blue Jay" and z["bird"]


def test_train_cross_validates_by_visit_and_predicts(tmp_path):
    main.embed_worker.embedder = FakeEmbedder()
    for i in range(6):
        add_visit(f"tj{i:03d}", "Blue Jay")
        add_visit(f"tc{i:03d}", "Black-capped Chickadee")
        add_visit(f"te{i:03d}", "Empty")
    add_visit("tn000", "Northern Cardinal")            # only 1 visit: listed as too few, not learned
    add_visit("tu000", "Blue Jay", label=False)        # unconfirmed: gets a model prediction

    ds = build_dataset(main.db, main.embed_worker)
    assert ds["X"].shape[1] == 2 * DIM and ds["X"].shape[0] == 19 * 3   # earlier tests' labels have no embeddings

    trainer = Trainer(main.db, main.embed_worker, tmp_path / "models")
    out = trainer.train()
    m = main.db.one("SELECT * FROM models WHERE id=?", out["model_id"])
    metrics = json.loads(m["metrics"])
    assert m["active"] == 1 and json.loads(m["classes"]) == ["Black-capped Chickadee", "Blue Jay", "Empty"]
    assert metrics["visit_accuracy"] >= 0.9 and metrics["cv_folds"] == 5
    assert metrics["too_few"] == {"Northern Cardinal": 1}
    assert metrics["baselines"]["vlm"]["visit_accuracy"] == 1.0
    assert len(metrics["confusion"]) == 3 and sum(map(sum, metrics["confusion"])) == 18
    assert len(metrics["mistakes"]) == 18 - sum(metrics["confusion"][i][i] for i in range(3))

    s = main.db.one("SELECT * FROM suggestions WHERE trace_id='tu000' AND source='model'")
    assert s["species"] == "Blue Jay" and s["model"] == f"v{out['model_id']}"

    c = TestClient(main.app)
    v = c.get("/api/visits/tu000").json()
    assert v["model"]["species"] == "Blue Jay" and all(x["source"] == "vlm" for x in v["suggestions"])
    st = c.get("/api/model").json()
    assert st["models"][0]["id"] == out["model_id"] and st["visits_per_species"]["Blue Jay"] >= 6
    out2 = trainer.train()
    assert c.post(f"/api/models/{out['model_id']}/activate").json()["ok"]
    assert main.db.one("SELECT id FROM models WHERE active=1")["id"] == out["model_id"] != out2["model_id"]


def test_confusion_keeps_the_wrong_visits_and_their_frames():
    """Each wrong cell of the confusion table can show its visits, frame by frame."""
    classes = ["Blue Jay", "Empty"]
    groups = np.array(["a", "a", "b", "b", "b"])
    y = np.array(["Blue Jay", "Blue Jay", "Empty", "Empty", "Blue Jay"])     # b: one frame tagged Blue Jay
    oof = np.array([[.9, .1], [.8, .2], [.2, .8], [.9, .1], [.95, .05]])     # b's two jay-ish frames outvote it
    m = metrics_from(oof, None, y, groups, classes, np.array(["Blue Jay"] * 2 + ["Empty"] * 3), [11, 12, 21, 22, 23])
    assert m["confusion"] == [[1, 0], [1, 0]]
    (w,) = m["mistakes"]
    assert (w["trace_id"], w["label"], w["predicted"]) == ("b", "Empty", "Blue Jay") and w["label_prob"] == 0.317
    assert [(f["id"], f["label"], f["predicted"]) for f in w["frames"]] ==         [(21, "Empty", "Empty"), (22, "Empty", "Blue Jay"), (23, "Blue Jay", "Blue Jay")]


def test_train_refuses_with_too_little_data(tmp_path):
    import pytest
    with main.db.tx() as c:
        c.execute("DELETE FROM labels")
    main.embed_worker.embedder = FakeEmbedder()
    add_visit("tx000", "Blue Jay")
    with pytest.raises(ValueError, match="at least 2 species"):
        Trainer(main.db, main.embed_worker, tmp_path).train()


def test_temperature_scaling_sharpens_underconfident_but_right_predictions():
    from wbs.train import calibrate, coverage, fit_temperature
    classes = ["A", "B", "C"]
    vy = np.array(["A", "B", "C"] * 10)
    vp = np.array([[0.55, 0.25, 0.2] if t == "A" else [0.25, 0.55, 0.2] if t == "B" else [0.2, 0.25, 0.55] for t in vy])
    T = fit_temperature(vp, vy, classes)
    assert T < 0.5
    cal = calibrate(vp, T)
    assert cal.max(axis=1).min() > 0.9 and np.allclose(cal.sum(axis=1), 1)
    assert coverage(vp, vy, classes, 0.75)["decided"] == 0.0
    assert coverage(cal, vy, classes, 0.75) == {"threshold": 0.75, "decided": 1.0, "accuracy": 1.0}


def test_auto_retrain_skips_activates_and_keeps(tmp_path):
    with main.db.tx() as c:
        c.execute("DELETE FROM labels")
        c.execute("DELETE FROM models")
    main.embed_worker.embedder = FakeEmbedder()
    for i in range(4):
        add_visit(f"aj{i:03d}", "Blue Jay")
        add_visit(f"ae{i:03d}", "Empty")
    t = Trainer(main.db, main.embed_worker, tmp_path / "m")
    first = t.auto_retrain(min_new=5)                       # no active model yet -> train and activate
    assert first["decision"] == "activated"
    v1 = first["model_id"]
    assert t.auto_retrain(min_new=5)["decision"] == "skipped"   # nothing new since

    time.sleep(0.01)
    for i in range(4):                                     # new confirmed visits, incl. a new species
        add_visit(f"bc{i:03d}", "Black-capped Chickadee")
        add_visit(f"bj{i:03d}", "Blue Jay")
    out = t.auto_retrain(min_new=5)
    assert out["decision"] == "activated" and "new visits" in out["reason"]   # v1 can't name chickadees
    assert main.db.one("SELECT id FROM models WHERE active=1")["id"] == out["model_id"] != v1
    row = main.db.one("SELECT kind, metrics FROM models WHERE id=?", out["model_id"])
    assert row["kind"] == "auto" and json.loads(row["metrics"])["auto"]["decision"] == "activated"

    # a candidate that is clearly worse on fresh data is NOT activated
    good = out["model_id"]
    time.sleep(0.01)
    for i in range(6):
        add_visit(f"zz{i:03d}", "Empty", noise=3.0)       # pure noise labelled Empty: candidate CV drops
    worse = t.auto_retrain(min_new=5, tolerance=-1.0)       # tolerance < 0: candidate must beat active by 100 pts
    assert worse["decision"] == "kept active"
    assert main.db.one("SELECT id FROM models WHERE active=1")["id"] == good


def test_square_crop_box_and_feature_uses_crop():
    from wbs.detect import square_crop_box
    from wbs.embed import frame_feature
    l, t, r, b = square_crop_box([0.1, 0.2, 0.2, 0.4], 2304, 1296)
    assert r - l == b - t and 0 <= l and 0 <= t and r <= 2304 and b <= 1296
    assert (r - l) >= 0.2 * 1296 * 1.3 - 2                          # box height x margin
    l, t, r, b = square_crop_box([0.95, 0.9, 1.0, 1.0], 2304, 1296)    # near the corner: stays inside
    assert r <= 2304 and b <= 1296 and r - l == b - t
    views5 = unit(RNG.normal(size=(5, DIM)))
    assert np.allclose(frame_feature(views5, 1)[:DIM], views5[4])      # 5th view (crop) wins
    views4 = views5[:4]
    assert np.allclose(frame_feature(views4, 2)[:DIM], views4[2])


def test_embed_frame_detector_fallback_and_reembed(tmp_path):
    from PIL import Image
    from wbs.embed import EMB_VERSION, EmbedWorker

    class FakeDetector:
        def __init__(self):
            self.seen = []

        def find(self, img, motion_box_json):
            self.seen.append(motion_box_json)
            return {"label": None, "score": None, "box": json.loads(motion_box_json), "source": "motion"} \
                if motion_box_json else None

    class FakeImageEmbedder(FakeEmbedder):
        def __init__(self):
            self.crops = []

        def embed_image(self, path, crop_box=None, img=None):
            self.crops.append(crop_box)
            return unit(RNG.normal(size=(5 if crop_box else 4, DIM)))

    det, emb = FakeDetector(), FakeImageEmbedder()
    w = EmbedWorker(main.settings, main.db, emb, detector=det)
    trace = "tdet001"
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time(), "time": "x"})
    p = main.settings.image_dir / "visits" / trace
    p.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 360)).save(p / "a.jpg")
    Image.new("RGB", (640, 360)).save(p / "b.jpg")
    fa = main.db.add_frame(trace, "clip", f"visits/{trace}/a.jpg", None, 1.0, 0.5, 640, 360, [0.4, 0.5, 0.6, 0.9])
    fb = main.db.add_frame(trace, "clip", f"visits/{trace}/b.jpg", None, 2.0, 0.5, 640, 360, None)
    main.db.set_visit(trace, status="prelabelled")
    with main.db.tx() as c:   # frame b already has an OLD (version 1) embedding: must be redone
        c.execute("INSERT INTO embeddings(frame_id, embedder, views, dim, data, created, version) VALUES (?,?,?,?,?,?,1)",
                  (fb, "bioclip-2", 4, DIM, to_blob(unit(RNG.normal(size=(4, DIM)))), time.time()))
        c.execute("UPDATE visits SET quiet=0 WHERE trace_id=?", (trace,))
    w.run_once(limit=50)
    rows = {r["frame_id"]: r for r in main.db.q("SELECT * FROM embeddings WHERE frame_id IN (?,?)", fa, fb)}
    assert rows[fa]["views"] == 5 and rows[fa]["version"] == EMB_VERSION
    assert rows[fb]["views"] == 4 and rows[fb]["version"] == EMB_VERSION
    d = main.db.one("SELECT * FROM detections WHERE frame_id=?", fa)
    assert d["source"] == "motion" and (d["x1"], d["y2"]) == (0.4, 0.9)
    assert main.db.one("SELECT 1 FROM detections WHERE frame_id=?", fb) is None
    v = TestClient(main.app).get(f"/api/visits/{trace}").json()
    fr = {f["id"]: f for f in v["frames"]}
    assert fr[fa]["det_source"] == "motion" and fr[fb]["x1"] is None


def test_label_checks_queue_keep_and_exclude(tmp_path):
    with main.db.tx() as c:
        c.execute("DELETE FROM labels")
        c.execute("DELETE FROM models")
    main.embed_worker.embedder = FakeEmbedder()
    for i in range(5):
        add_visit(f"cj{i:03d}", "Blue Jay")
        add_visit(f"cc{i:03d}", "Black-capped Chickadee")
    add_visit("cwrong", "Black-capped Chickadee")
    # a jay-looking visit that was labelled chickadee by mistake
    with main.db.tx() as c:
        c.execute("DELETE FROM labels WHERE trace_id='cwrong'")
    ids = [r["id"] for r in main.db.q("SELECT id FROM frames WHERE trace_id='cwrong'")]
    with main.db.tx() as c:
        for fid in ids:
            c.execute("UPDATE embeddings SET data=? WHERE frame_id=?",
                      (to_blob(unit(CENTRES["Blue Jay"] + RNG.normal(scale=0.3, size=(4, DIM)))), fid))
    main.db.set_label("cwrong", "Black-capped Chickadee", ids, None, "confirmed")
    add_visit("cother", "Empty")
    main.db.set_label("cother", "Other animal", [main.db.one("SELECT id FROM frames WHERE trace_id='cother'")["id"]],
                      None, "corrected")

    t = Trainer(main.db, main.embed_worker, tmp_path)
    t.train()
    checks = {r["trace_id"]: r for r in main.db.q("SELECT * FROM label_checks")}
    assert checks["cwrong"]["predicted"] == "Blue Jay" and checks["cwrong"]["p_label"] < 0.5
    c = TestClient(main.app)
    q = c.get("/api/visits?queue=check&limit=100").json()
    assert q["visits"][0]["trace_id"] == "cwrong"                       # most doubtful first
    assert q["visits"][0]["check"]["predicted"] == "Blue Jay"
    assert c.post("/api/visits/cwrong/keep").json()["ok"]
    assert "cwrong" not in [v["trace_id"] for v in c.get("/api/visits?queue=check&limit=100").json()["visits"]]

    # Exclude: out of training, queues and counts; Restore brings it back
    assert c.post("/api/visits/cother/exclude", json={"excluded": True}).json()["excluded"] is True
    assert "cother" in [v["trace_id"] for v in c.get("/api/visits?queue=excluded").json()["visits"]]
    assert "cother" not in [v["trace_id"] for v in c.get("/api/visits?queue=labelled&limit=100").json()["visits"]]
    st = c.get("/api/stats").json()
    assert st["excluded_visits"] >= 1 and "Other animal" not in [s["species"] for s in st["by_species"]]
    assert all(g != "cother" for g in build_dataset(main.db, main.embed_worker)["groups"])
    assert c.get("/api/model").json()["visits_per_species"].get("Other animal") is None
    c.post("/api/visits/cother/exclude", json={"excluded": False})
    assert "cother" in [v["trace_id"] for v in c.get("/api/visits?queue=labelled&limit=100").json()["visits"]]


def test_species_season_levels():
    from datetime import datetime
    from wbs.species import season_level
    assert season_level("Black-capped Chickadee", 11) == 2
    assert season_level("Baltimore Oriole", 1) == 0 and season_level("Baltimore Oriole", 6) == 2
    assert season_level("Squirrel", 5) is None
    sp = {s["name"]: s for s in TestClient(main.app).get("/api/species").json()}
    assert sp["Blue Jay"]["season"] == 2 and sp["Blue Jay"]["season_text"] == "expected"
    assert sp["Empty"]["season"] is None
    assert sp["Ruby-throated Hummingbird"]["season"] == season_level("Ruby-throated Hummingbird", datetime.now().month)


def test_species_families():
    sp = {s["name"]: s for s in TestClient(main.app).get("/api/species").json()}
    assert (sp["Downy Woodpecker"]["family"], sp["Downy Woodpecker"]["family_name"]) == ("Picidae", "Woodpeckers")
    assert sp["Squirrel"]["family"] == "Sciuridae" and sp["Empty"]["family"] is None
    assert all(s["family"] for s in sp.values() if s["kind"] == "bird" and s["name"] in __import__("wbs.species", fromlist=["SEASON"]).SEASON)


def test_retrain_every_n_days(tmp_path, monkeypatch):
    """Due at the retrain hour once the setting's days have passed since the last model, whoever trained it."""
    from types import SimpleNamespace
    t = Trainer(main.db, main.embed_worker, tmp_path)
    at = lambda days_ago, hour: time.mktime((2026, 11, 20 - days_ago, hour, 10, 0, 0, 0, -1))  # noqa: E731
    now = at(0, 2)
    with main.db.tx() as c:
        c.execute("UPDATE models SET created=? WHERE 1", (at(3, 2),))      # every model: last trained 3 days ago
        if not c.execute("SELECT 1 FROM models").fetchone():
            c.execute("INSERT INTO models(created, embedder, kind, classes, n_visits, n_frames, metrics, path) "
                      "VALUES (?,?,?,?,?,?,?,?)", (at(3, 2), "x", "logreg", "[]", 0, 0, "{}", ""))
    s = lambda **kw: SimpleNamespace(**{"auto_train": True, "auto_train_hour": 2, "auto_train_days": 1, **kw})  # noqa: E731
    assert t.retrain_due(s(), now)                         # nightly: due
    assert t.retrain_due(s(auto_train_days=3), now)        # 3 days: exactly due, at the same hour
    assert not t.retrain_due(s(auto_train_days=4), now)    # 4 days: not yet
    assert not t.retrain_due(s(), at(0, 3))                # wrong hour
    assert not t.retrain_due(s(auto_train=False), now)     # turned off
