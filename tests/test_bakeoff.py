import time

from wbs import main
from wbs.bakeoff import Bakeoff, sample_visits, score
from wbs.config import settings


class FakeLM:
    """'good' answers with the true species (from the frame file contents), 'bad' always says Blue Jay,
    'flaky' raises on every other call."""

    def __init__(self):
        self.s = settings
        self.calls = 0
        self.http = self

    def get(self, url, timeout):
        class R:
            @staticmethod
            def json():
                return {"data": [{"id": "good", "type": "vlm", "state": "loaded"},
                                 {"id": "bad", "type": "vlm", "state": "not-loaded"},
                                 {"id": "flaky", "type": "vlm", "state": "not-loaded"},
                                 {"id": "text-only", "type": "llm"}]}
        return R()

    def post(self, *a, **k):
        return None

    def ask(self, model, jpeg):
        self.calls += 1
        truth = jpeg.decode(errors="ignore").split("|")[1]
        if model == "flaky" and self.calls % 2:
            raise RuntimeError("model crashed")
        species = truth if model in ("good", "flaky") else "Blue Jay"
        return {"bird_present": species != "Empty", "species": None if species == "Empty" else species,
                "confidence": 0.9}, "{}"


def seed(trace, species):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time(), "time": "x"})
    ids = []
    for k in range(3):
        p = settings.image_dir / "visits" / trace / f"b{k}.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f"jpg|{species}|".encode())
        ids.append(main.db.add_frame(trace, "clip", str(p.relative_to(settings.image_dir)), None, k, 1 - k / 10, 1, 1))
    main.db.set_label(trace, species, ids, None, "confirmed")


def test_bakeoff_end_to_end():
    with main.db.tx() as c:
        c.execute("DELETE FROM labels")
    for i in range(9):
        seed(f"bk_jay{i}", "Blue Jay")
    for i in range(3):
        seed(f"bk_chk{i}", "Black-capped Chickadee")
        seed(f"bk_emp{i}", "Empty")

    sample = sample_visits(main.db, per_species=4, total=40)
    counts = {}
    for s in sample:
        counts[s["species"]] = counts.get(s["species"], 0) + 1
        assert len(s["frames"]) == 2
    assert counts == {"Blue Jay": 4, "Black-capped Chickadee": 3, "Empty": 3}     # stratified, capped per species

    lm = FakeLM()
    b = Bakeoff(main.db, lm, main.prelabeler, settings.image_dir, lambda n: main.canonical(n, main.species_index()))
    assert [m["id"] for m in b.models()] == ["good", "bad", "flaky"]              # vision models only
    assert b.start(["good", "bad", "flaky"], per_species=4)
    for _ in range(200):
        if b.status["state"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert b.status["state"] == "done", b.status
    res = {r["model"]: r for r in b.results()}
    assert res["good"]["visit_accuracy"] == 1.0 and res["good"]["json_ok"] == 1.0
    assert res["bad"]["visit_accuracy"] == 0.4                                   # right only on the 4 Blue Jays
    assert res["flaky"]["status"] == "done" and res["flaky"]["json_ok"] == 0.5    # errors count as invalid answers
    assert main.prelabeler.paused is False


def test_score_counts_bird_presence():
    s = score([{"trace_id": "t", "species": "Empty", "frames": [
        {"result": {"bird_present": True, "species": "Blue Jay"}, "seconds": 1.0},
        {"result": None, "seconds": 3.0}]}], lambda n: n)
    assert s["visit_accuracy"] == 0.0 and s["bird_accuracy"] == 0.0 and s["json_ok"] == 0.5
    assert s["seconds_per_frame"] == 2.0 and s["mistakes"][0]["model"] == "Blue Jay"


def teardown_module(module):
    with main.db.tx() as c:
        c.execute("DELETE FROM visits WHERE trace_id LIKE 'bk_%'")
        c.execute("DELETE FROM bakeoff")
