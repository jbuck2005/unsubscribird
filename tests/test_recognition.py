import json
import time

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings
from wbs.recognition import Recognizer, decide, event_type


def test_decide_rules():
    m_hi = {"species": "Blue Jay", "confidence": 0.9}
    m_lo = {"species": "Blue Jay", "confidence": 0.5}
    v_hi = {"species": "Northern Cardinal", "confidence": 0.95}
    v_lo = {"species": "Northern Cardinal", "confidence": 0.6}
    assert decide(m_hi, v_hi, 0.75, 0.8)["source"] == "model"
    d = decide(m_lo, v_hi, 0.75, 0.8)                  # model unsure, LM Studio sure (e.g. a species the model lacks)
    assert (d["species"], d["source"]) == ("Northern Cardinal", "lmstudio")
    d = decide(m_lo, v_lo, 0.75, 0.8)
    assert (d["species"], d["source"], d["guess"]) == ("Uncertain", "uncertain", "Northern Cardinal")
    assert decide(None, None, 0.75, 0.8)["guess"] is None
    assert decide(None, v_hi, 0.75, 0.8)["source"] == "lmstudio"   # no model trained yet


def test_unknown_species_goes_to_lmstudio_even_if_model_is_sure():
    classes = ["Blue Jay", "Black-capped Chickadee", "Empty"]
    d = decide({"species": "Blue Jay", "confidence": 0.97}, {"species": "Northern Cardinal", "confidence": 0.95},
               0.75, 0.8, classes)
    assert (d["species"], d["source"]) == ("Northern Cardinal", "lmstudio")
    d = decide({"species": "Blue Jay", "confidence": 0.97}, {"species": "Black-capped Chickadee", "confidence": 0.95},
               0.75, 0.8, classes)                       # both know the species: the (better) model decides
    assert (d["species"], d["source"]) == ("Blue Jay", "model")
    d = decide({"species": "Blue Jay", "confidence": 0.97}, {"species": "Northern Cardinal", "confidence": 0.6},
               0.75, 0.8, classes)                       # LM Studio not sure about the new species: model
    assert d["source"] == "model"


def test_event_types():
    assert [event_type(s) for s in ("Blue Jay", "Empty", "Squirrel", "Uncertain", "Unknown bird")] == \
        ["bird", "empty", "other_animal", "uncertain", "bird"]


class Sink:
    def __init__(self):
        self.msgs = []

    def __call__(self, topic, payload, retain):
        self.msgs.append((topic, payload, retain))

    def last(self, topic):
        return next((p for t, p, _ in reversed(self.msgs) if t == topic), None)


def visit(trace, *, vlm=None, model=None, created_ago=0, frames=1):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 30,
                          "time": "2026-11-05T11:00:00-05:00", "bird": "Unidentified"})
    p = settings.image_dir / "visits" / trace
    p.mkdir(parents=True, exist_ok=True)
    ids = []
    for k in range(frames):
        f = p / f"f{k}.jpg"
        f.write_bytes(b"\xff\xd8" + trace.encode() + b"\xff\xd9")
        fid = main.db.add_frame(trace, "clip", str(f.relative_to(settings.image_dir)), None, float(k), 0.5, 10, 10)
        with main.db.tx() as c:   # pretend it has been embedded
            c.execute("INSERT INTO embeddings(frame_id, embedder, views, dim, data, created) VALUES (?,?,?,?,?,?)",
                      (fid, "fake", 1, 1, b"\0\0\0\0", time.time()))
        ids.append(fid)
    if vlm:
        main.db.add_suggestion(trace, ids[0], "vlm", "m", {"bird_present": vlm[0] != "Empty", "species": vlm[0],
                                                          "confidence": vlm[1]}, "")
        main.db.set_visit(trace, status="prelabelled")
    else:
        main.db.set_visit(trace, status="frames")
    if model:
        main.db.add_suggestion(trace, None, "model", "v9", {"species": model[0], "confidence": model[1]}, "")
    with main.db.tx() as c:
        c.execute("UPDATE visits SET created=? WHERE trace_id=?", (time.time() - created_ago, trace))


def recognizer(sink):
    return Recognizer(settings, main.db, sink, canonical=lambda n: main.canonical(n, main.species_index()))


def test_waits_for_model_and_lmstudio_then_publishes():
    with main.db.tx() as c:
        c.execute("DELETE FROM models")
        c.execute("INSERT INTO models(created, embedder, kind, classes, n_visits, n_frames, metrics, path, active) "
                  "VALUES (?,?,?,?,?,?,?,?,1)", (time.time(), "x", "logreg", '["Blue Jay", "Empty"]', 0, 0, "{}",
                                                    "/nonexistent"))
        c.execute("UPDATE visits SET rec_at=0")            # ignore visits from other tests
    sink = Sink()
    r = recognizer(sink)
    visit("rc001", vlm=("Blue Jay", 0.95))                 # model hasn't predicted yet -> wait
    visit("rc002", model=("Blue Jay", 0.9))                # LM Studio not done, only just created -> wait
    visit("rc003", model=("Blue Jay", 0.9), created_ago=3600)      # LM Studio never came: publish anyway
    visit("rc004", vlm=("black-capped chickadee", 0.95), model=("Blue Jay", 0.4))
    visit("rc005", vlm=("Empty", 1.0), model=("Empty", 0.99))
    visit("rc006", vlm=("Blue Jay", 0.5), model=("Blue Jay", 0.5))
    assert r.run_once() == 4
    rec = {t: main.db.one("SELECT rec_species, rec_source, rec_guess FROM visits WHERE trace_id=?", t)
           for t in ("rc001", "rc002", "rc003", "rc004", "rc005", "rc006")}
    assert rec["rc001"]["rec_species"] is None and rec["rc002"]["rec_species"] is None
    assert tuple(rec["rc003"]) == ("Blue Jay", "model", None)
    assert tuple(rec["rc004"]) == ("Black-capped Chickadee", "lmstudio", None)   # name normalised
    assert tuple(rec["rc005"]) == ("Empty", "model", None)
    assert tuple(rec["rc006"]) == ("Uncertain", "uncertain", "Blue Jay")

    events = [json.loads(p)["event_type"] for t, p, retain in sink.msgs if t == "unsubscribird/event"]
    assert events == ["bird", "bird", "empty", "uncertain"]
    assert not any(retain for t, _, retain in sink.msgs if t == "unsubscribird/event")
    last_bird = json.loads(sink.last("unsubscribird/last_bird"))
    assert last_bird["species"] == "Black-capped Chickadee" and last_bird["review_url"].endswith("?visit=rc004")
    assert sink.last("unsubscribird/image") == b"\xff\xd8rc004\xff\xd9"      # photo of the last BIRD, not the empty visit
    assert json.loads(sink.last("unsubscribird/last_visit"))["species"] == "Uncertain"
    today = json.loads(sink.last("unsubscribird/today"))
    assert today["by_species"] == {"Blue Jay": 1, "Black-capped Chickadee": 1} or today["species"] >= 2
    assert today["uncertain"] >= 1 and today["empty"] >= 1
    assert today["recent"][0]["trace_id"] in ("rc006", "rc005", "rc004", "rc003") and len(today["recent"]) <= 10
    assert len(json.dumps(today)) < 16000                     # HA keeps attributes under 16 kB
    assert r.run_once() == 0                                # each visit is decided once


def test_discovery_and_uncertain_queue_first():
    sink = Sink()
    recognizer(sink).publish_discovery()
    configs = {t: json.loads(p) for t, p, _ in sink.msgs if t.endswith("/config")}
    assert len(configs) >= 8 and all(c["device"]["identifiers"] == ["unsubscribird"] for c in configs.values())
    assert all(c["availability_topic"] == "unsubscribird/status" for t, c in configs.items() if "/sighting/" not in t)
    assert sink.last("unsubscribird/status") == "online"
    c = TestClient(main.app)
    q = c.get("/api/visits?queue=review&limit=100").json()["visits"]
    uncertain = [v["trace_id"] for v in q if v.get("rec_source") == "uncertain"]
    assert uncertain and q[0]["trace_id"] == uncertain[0]             # uncertain visits come first
    assert "rc006" in [v["trace_id"] for v in c.get("/api/visits?queue=uncertain").json()["visits"]]


def teardown_module(module):
    """Leave no fake model / fake embeddings behind for other test files."""
    with main.db.tx() as c:
        c.execute("DELETE FROM models WHERE path='/nonexistent'")
        c.execute("DELETE FROM embeddings WHERE embedder='fake'")
        c.execute("DELETE FROM visits WHERE trace_id LIKE 'rc0%'")


def test_backlog_sets_state_but_fires_no_event():
    sink = Sink()
    visit("rc010", vlm=("Blue Jay", 0.95))
    with main.db.tx() as c:
        c.execute("DELETE FROM models")
        c.execute("UPDATE visits SET rec_at=0 WHERE trace_id != 'rc010'")       # only this visit is pending
        c.execute("UPDATE visits SET ts=? WHERE trace_id='rc010'", (time.time() - 3 * 3600,))
    recognizer(sink).run_once()
    assert json.loads(sink.last("unsubscribird/last_bird"))["trace_id"] == "rc010"
    assert sink.last("unsubscribird/event") is None


def test_confirmed_label_wins_and_relabel_updates_ha_without_event():
    sink = Sink()
    r = recognizer(sink)
    visit("rc020", vlm=("European Starling", 0.95))                 # LM Studio confidently wrong
    with main.db.tx() as c:
        c.execute("DELETE FROM models")
        c.execute("UPDATE visits SET rec_at=0 WHERE trace_id != 'rc020'")
    r.run_once()
    assert json.loads(sink.last("unsubscribird/last_bird"))["species"] == "European Starling"
    n_events = sum(t == "unsubscribird/event" for t, _, _ in sink.msgs)
    main.db.set_label("rc020", "Black-capped Chickadee", [main.db.one("SELECT id FROM frames WHERE trace_id='rc020'")["id"]],
                      None, "corrected")
    r.refresh("rc020")
    lb = json.loads(sink.last("unsubscribird/last_bird"))
    assert (lb["species"], lb["source"], lb["confidence"]) == ("Black-capped Chickadee", "confirmed", 1.0)
    assert sum(t == "unsubscribird/event" for t, _, _ in sink.msgs) == n_events     # no new event
    assert main.db.one("SELECT rec_species FROM visits WHERE trace_id='rc020'")["rec_species"] == "Black-capped Chickadee"


def test_first_today_and_first_ever_flags_and_event_after_photo():
    sink = Sink()
    r = recognizer(sink)
    with main.db.tx() as c:
        c.execute("DELETE FROM models")
        c.execute("UPDATE visits SET rec_at=0")
    visit("rc030", vlm=("Northern Cardinal", 0.95))
    with main.db.tx() as c:
        c.execute("UPDATE visits SET ts=? WHERE trace_id='rc030'", (time.time() - 120,))
    visit("rc031", vlm=("Northern Cardinal", 0.95))
    visit("rc032", vlm=("Empty", 1.0))
    r.run_once()
    ev = {json.loads(p)["trace_id"]: json.loads(p) for t, p, _ in sink.msgs if t == "unsubscribird/event"}
    assert (ev["rc030"]["first_today"], ev["rc030"]["first_ever"]) == (True, True)
    assert (ev["rc031"]["first_today"], ev["rc031"]["first_ever"]) == (False, False)
    assert ev["rc032"]["first_today"] is False                       # not a bird
    topics = [t for t, _, _ in sink.msgs]
    i_event = topics.index("unsubscribird/event")
    assert topics.index("unsubscribird/image") < i_event               # photo already updated when the event fires


def test_species_gallery():
    from PIL import Image
    sink = Sink()
    r = recognizer(sink)
    with main.db.tx() as c:
        c.execute("UPDATE visits SET rec_at=NULL")
    now = time.time()

    def seen(trace, species, ago, box=None):
        main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": now - ago, "time": None})
        p = settings.image_dir / "visits" / trace
        p.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1280, 720), (30, 120, 200)).save(p / "f.jpg")
        fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 1280, 720)
        if box:
            with main.db.tx() as c:
                c.execute("INSERT INTO detections(frame_id, source, label, score, x1, y1, x2, y2, created) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (fid, "owlvit", "bird", 0.8, *box, now))
        main.db.set_visit(trace, rec_species=species, rec_source="model", rec_conf=0.9, rec_at=now)

    seen("g01", "Blue Jay", 3600 * 30, box=[0.1, 0.1, 0.3, 0.5])   # yesterday-ish
    seen("g02", "Black-capped Chickadee", 600)
    seen("g03", "Blue Jay", 120, box=[0.4, 0.2, 0.6, 0.6])          # newest jay
    seen("g04", "Empty", 60)
    seen("g05", "Uncertain", 30)
    seen("g06", "Northern Cardinal", 8 * 86400)                       # outside the 7-day window
    g = r.gallery(now)
    assert [x["name"] for x in g] == ["Blue Jay", "Black-capped Chickadee"]
    jay = g[0]
    assert jay["trace_id"] == "g03" and jay["week"] == 2 and jay["image"] == "image.unsubscribird_blue_jay_photo"
    assert jay["today"] >= 1

    r.publish_gallery()
    cfgs = [t for t, _, _ in sink.msgs if t.endswith("/config")]
    assert "homeassistant/image/unsubscribird/species_blue_jay/config" in cfgs
    photo = sink.last("unsubscribird/species/blue_jay/image")
    im = Image.open(__import__("io").BytesIO(photo))
    assert im.size[0] == im.size[1] and im.size[0] <= 640           # square crop around the bird
    gal = json.loads(sink.last("unsubscribird/gallery"))
    assert gal["count"] == 2 and gal["days"] == 7

    n = len(sink.msgs)
    r.publish_gallery()                                              # nothing new: only the summary again
    assert [t for t, _, _ in sink.msgs[n:]] == ["unsubscribird/gallery"]
    r.publish_discovery()                                            # HA restart: photos re-sent
    assert sink.last("unsubscribird/species/black_capped_chickadee/image") is not None
    with main.db.tx() as c:
        c.execute("DELETE FROM visits WHERE trace_id LIKE 'g0%'")


def test_sighting_event_species_typed_and_no_empty():
    sink = Sink()
    r = recognizer(sink)
    with main.db.tx() as c:
        c.execute("DELETE FROM models")
        c.execute("UPDATE visits SET rec_at=0")
    r.publish_discovery()
    cfg = json.loads(sink.last("homeassistant/event/unsubscribird/sighting/config"))
    assert "availability_topic" not in cfg and "Blue Jay" in cfg["event_types"] and "Empty" not in cfg["event_types"]
    visit("rc040", vlm=("Blue Jay", 0.95))
    visit("rc041", vlm=("Empty", 1.0))
    visit("rc042", vlm=("Snowy Owl", 0.97))           # not in the species list: event_types must grow first
    r.run_once()
    sightings = [json.loads(p)["event_type"] for t, p, _ in sink.msgs if t == "unsubscribird/sighting"]
    assert sightings == ["Blue Jay", "Snowy Owl"]
    topics = [t for t, _, _ in sink.msgs]
    owl_cfg_i = max(i for i, (t, p, _) in enumerate(sink.msgs)
                    if t.endswith("/sighting/config") and "Snowy Owl" in json.loads(p)["event_types"])
    owl_evt_i = max(i for i, (t, p, _) in enumerate(sink.msgs) if t == "unsubscribird/sighting")
    assert owl_cfg_i < owl_evt_i
    today = json.loads(sink.last("unsubscribird/today"))
    assert [s["species"] for s in today["sightings"]][:2] == ["Snowy Owl", "Blue Jay"]
    assert all(s["species"] != "Empty" for s in today["sightings"]) and len(json.dumps(today)) < 16000


def test_day_colours_unique_per_species_in_order_of_first_sighting():
    from wbs.recognition import day_colours
    c = day_colours(["Blue Jay", "Black-capped Chickadee", "Blue Jay", "Uncertain", "Northern Cardinal"])
    assert c == {"Blue Jay": "🔵", "Black-capped Chickadee": "🟢", "Uncertain": "❔", "Northern Cardinal": "🟠"}
