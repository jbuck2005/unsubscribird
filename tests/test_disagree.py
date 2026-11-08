import time

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings

IDS = []


def teardown_module():
    with main.db.tx() as c:
        for t in IDS:
            c.execute("DELETE FROM visits WHERE trace_id=?", (t,))


def visit(trace, vlm=None, model=None, label=None, ago=0, reject=False):
    """vlm / model: (species, confidence); vlm species None = LM Studio saw no bird."""
    IDS.append(trace)
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 60 - ago, "time": "t",
                          "bird": "x"})
    p = settings.image_dir / "visits" / "dis" / trace
    p.mkdir(parents=True, exist_ok=True)
    (p / "f0.jpg").write_bytes(b"jpg")
    fid = main.db.add_frame(trace, "clip", str((p / "f0.jpg").relative_to(settings.image_dir)), None, 0.0, 0.5, 10, 10)
    if vlm:
        main.db.add_suggestion(trace, fid, "vlm", "m", {"bird_present": vlm[0] is not None, "species": vlm[0],
                                                        "confidence": vlm[1]}, "")
    if model:
        main.db.add_suggestion(trace, None, "model", "v1", {"species": model[0], "confidence": model[1]}, "")
    main.db.set_visit(trace, status="prelabelled")
    if label:
        main.db.set_label(trace, label, [fid], None, "confirmed")
    if reject:
        with main.db.tx() as c:
            c.execute("UPDATE frames SET rejected=1 WHERE id=?", (fid,))


def queue(c):
    return [v["trace_id"] for v in c.get("/api/visits?queue=disagree&limit=100").json()["visits"]]


def test_disagree_queue():
    visit("dis-jay-squirrel", vlm=(None, 0.9), model=("Blue Jay", 0.99))      # LM Studio: no bird -> Empty
    visit("dis-new-species", vlm=("White-breasted Nuthatch", 0.9), model=("Black-capped Chickadee", 0.8), ago=10)
    visit("dis-agree", vlm=("blue jay", 0.9), model=("Blue Jay", 0.99))       # same bird, other spelling
    visit("dis-no-model", vlm=("Blue Jay", 0.9))
    visit("dis-labelled", vlm=(None, 0.9), model=("Blue Jay", 0.99), label="Blue Jay")   # reviewed: Check labels' job
    visit("dis-rejected-frame", vlm=(None, 0.9), model=("Blue Jay", 0.99), reject=True)  # its LM Studio answer is gone
    c = TestClient(main.app)
    got = queue(c)
    mine = [t for t in got if t.startswith("dis-")]
    assert mine == ["dis-jay-squirrel", "dis-new-species"]                     # newest first, nothing else
    r = c.get("/api/visits?queue=disagree&limit=0").json()
    assert r["total"] == len(got) and r["visits"] == []
    v = c.get("/api/visits/dis-new-species").json()
    assert v["disagree"] is True and c.get("/api/visits/dis-agree").json()["disagree"] is False
    assert "dis-jay-squirrel" in [x["trace_id"] for x in c.get("/api/visits?queue=review&limit=100").json()["visits"]]
    fid = c.get("/api/visits/dis-jay-squirrel").json()["frames"][0]["id"]
    assert c.post("/api/visits/dis-jay-squirrel/label", json={"species": "Blue Jay", "frame_ids": [fid]}).status_code == 200
    assert "dis-jay-squirrel" not in queue(c)                                  # confirmed: leaves the queue
