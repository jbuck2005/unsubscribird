"""Keep sure Empty visits out of the review queue, but keep a few a day as training negatives.

Most visits are the wind, a light change or a bird that already left. Reviewing every one of them adds little to
the training data, so a visit that every signal calls Empty is *filed*: it leaves To review for the Filed Empty
queue. It still counts as Empty (as it did before), but it isn't training data unless a person confirms it.

A visit is filed only when all of these agree (see sure_empty):
- the frame picker saw nothing move, or LM Studio called every frame empty (and at least SURE_VLM sure);
- the trained model, when one is active and ran, says Empty at SURE_MODEL or more (with an active model, a visit
  where something moved waits for the model's answer);
- the detector (OWL-ViT) boxed nothing in any frame;
- nobody flagged the visit.
Anything else stays in To review: those doubtful empties are the hard negatives worth a person's look.

Each day, `empty_review_per_day` of the previous day's filed visits come back to To review as a *sample*, spread
over the day: light and shadows change an empty feeder most, so the 3-hour blocks with the fewest confirmed Empty
visits in the last two weeks go first, and within a block the clip with the most movement (the hardest negative).

visits.triage: NULL = not filed, 'filed', 'sample' (picked back for review) or 'kept' (a person sent it back;
never filed again). visits.triaged = when. Turning the setting off sends every unconfirmed filed visit back.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict

from .prelabel import consensus

LOG = logging.getLogger("unsub.triage")
DAY = 86400
INTERVAL_S = 120
SURE_MODEL = 0.9
SURE_VLM = 0.7
BLOCK_H = 3            # times of day are compared in blocks of this many hours
COVERAGE_DAYS = 14     # confirmed Empty visits this recent count towards a block's coverage
MAX_PER_PASS = 2000


def day_start(ts: float) -> float:
    t = time.localtime(ts)
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def block(ts: float) -> int:
    return time.localtime(ts).tm_hour // BLOCK_H


def sure_empty(db, v, has_model: bool) -> bool:
    """True when every signal says this unconfirmed visit is Empty (see the module docstring)."""
    if v["flagged"] is not None or v["excluded"]:
        return False
    active = {r["id"] for r in db.q("SELECT id FROM frames WHERE trace_id=? AND rejected=0", v["trace_id"])}
    if db.one("""SELECT 1 FROM detections d JOIN frames f ON f.id=d.frame_id
                 WHERE f.trace_id=? AND f.rejected=0 AND d.source='owlvit'""", v["trace_id"]):
        return False
    sugg = [dict(s) for s in db.q("""SELECT * FROM suggestions WHERE trace_id=? AND source IN ('vlm','motion')""",
                                  v["trace_id"]) if s["frame_id"] is None or s["frame_id"] in active]
    cons = consensus(sugg)
    if not cons or cons["species"].strip().lower() != "empty":
        return False
    if not v["quiet"] and (cons["confidence"] or 0) < SURE_VLM:
        return False
    model = db.one("SELECT species, confidence FROM suggestions WHERE trace_id=? AND source='model' ORDER BY id DESC",
                   v["trace_id"])
    if model:
        return (model["species"] or "").strip().lower() == "empty" and (model["confidence"] or 0) >= SURE_MODEL
    return not has_model or bool(v["quiet"])   # quiet clips skip the model; others wait for its answer


def file_sure_empties(db, limit: int = MAX_PER_PASS) -> int:
    """File the unconfirmed visits to review that are surely Empty. Returns how many were filed."""
    has_model = db.one("SELECT 1 FROM models WHERE active=1") is not None
    rows = db.q("""SELECT v.* FROM visits v LEFT JOIN labels l USING(trace_id)
                   WHERE v.status='prelabelled' AND l.trace_id IS NULL AND v.excluded=0 AND v.triage IS NULL
                   ORDER BY v.ts DESC LIMIT ?""", limit)
    sure = [v["trace_id"] for v in rows if sure_empty(db, v, has_model)]
    now = time.time()
    with db.tx() as c:
        c.executemany("UPDATE visits SET triage='filed', triaged=? WHERE trace_id=? AND triage IS NULL",
                      [(now, t) for t in sure])
    if sure:
        LOG.info("Filed %d sure Empty visit(s) out of To review", len(sure))
    return len(sure)


def coverage(db, now: float) -> dict[int, int]:
    """Confirmed Empty visits (and samples) of the last COVERAGE_DAYS days per time-of-day block."""
    rows = db.q("""SELECT v.ts FROM visits v LEFT JOIN labels l USING(trace_id)
                   WHERE v.excluded=0 AND v.ts >= ? AND (l.species='Empty' OR v.triage='sample')""",
                now - COVERAGE_DAYS * DAY)
    out: dict[int, int] = defaultdict(int)
    for r in rows:
        out[block(r["ts"])] += 1
    return out


def pick_sample(candidates: list, n: int, cover: dict[int, int]) -> list[str]:
    """n trace ids, one block at a time: least covered block first, then the clip that moved most in it."""
    by_block: dict[int, list] = defaultdict(list)
    for v in candidates:
        by_block[block(v["ts"])].append(v)
    for vs in by_block.values():
        vs.sort(key=lambda v: (-(v["activity"] or 0), v["ts"]))
    order = sorted(by_block, key=lambda b: (cover.get(b, 0), b))
    picked: list[str] = []
    while len(picked) < n and any(by_block.values()):
        for b in order:
            if by_block[b] and len(picked) < n:
                picked.append(by_block[b].pop(0)["trace_id"])
    return picked


def sample_day(db, n: int, now: float | None = None) -> int:
    """Send `n` of yesterday's filed visits back to To review, once per day. Returns how many."""
    now = now or time.time()
    end = day_start(now)
    start = day_start(end - DAY / 2)
    if n <= 0 or db.one("SELECT 1 FROM visits WHERE triage='sample' AND ts >= ? AND ts < ?", start, end):
        return 0
    rows = db.q("""SELECT v.trace_id, v.ts, v.activity FROM visits v LEFT JOIN labels l USING(trace_id)
                   WHERE v.triage='filed' AND l.trace_id IS NULL AND v.excluded=0 AND v.ts >= ? AND v.ts < ?""",
                start, end)
    picked = pick_sample(rows, n, coverage(db, now))
    with db.tx() as c:
        c.executemany("UPDATE visits SET triage='sample', triaged=? WHERE trace_id=?", [(now, t) for t in picked])
    if picked:
        LOG.info("Sent %d of yesterday's filed Empty visit(s) back to To review as training negatives", len(picked))
    return len(picked)


def unfile_all(db) -> int:
    """Auto-filing was turned off: every unconfirmed filed visit goes back to To review."""
    with db.tx() as c:
        n = c.execute("""UPDATE visits SET triage=NULL, triaged=NULL WHERE triage='filed'
                         AND trace_id NOT IN (SELECT trace_id FROM labels)""").rowcount
    if n:
        LOG.info("Auto-filing is off: %d filed Empty visit(s) are back in To review", n)
    return n


def run_pass(settings, db, now: float | None = None) -> dict:
    if not settings.empty_auto_file:
        return {"filed": 0, "sampled": 0, "unfiled": unfile_all(db)}
    filed = file_sure_empties(db)
    return {"filed": filed, "sampled": sample_day(db, settings.empty_review_per_day, now), "unfiled": 0}


class Triage:
    def __init__(self, settings, db) -> None:
        self.s, self.db = settings, db
        self.stop = threading.Event()
        self.last: dict | None = None

    def stats(self) -> dict:
        rows = {r["triage"]: r["n"] for r in self.db.q("""SELECT v.triage, COUNT(*) n FROM visits v
                   LEFT JOIN labels l USING(trace_id) WHERE v.triage IS NOT NULL AND l.trace_id IS NULL
                   AND v.excluded=0 GROUP BY v.triage""")}
        return {"on": self.s.empty_auto_file, "per_day": self.s.empty_review_per_day,
                "filed": rows.get("filed", 0), "samples_to_review": rows.get("sample", 0), "last_pass": self.last}

    def start(self) -> None:
        def loop():
            while not self.stop.is_set():
                try:   # reads the settings each time, so a change on the Settings page applies at the next pass
                    self.last = run_pass(self.s, self.db)
                except Exception:
                    LOG.exception("Empty triage pass failed")
                self.stop.wait(INTERVAL_S)
        threading.Thread(target=loop, name="triage", daemon=True).start()
