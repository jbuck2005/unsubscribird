"""Re-pick the frames of visits processed by an older frame picker, and re-attach their confirmed labels.

    docker exec unsubscribird python -m wbs.repick            # dry run: what would change
    docker exec unsubscribird python -m wbs.repick --apply    # do it

Targets visits with a clip but no recorded activity score (processed before 0.7; the camera wake-up exposure
fix came in 0.6, so several of these kept a frame with no bird in it). Per visit:
  1. pick frames from the clip with the current picker; old clip frames that aren't picked again are marked
     rejected (kept on disk, never used for training);
  2. ask the LM Studio model (if one is loaded) about each new frame, so review shows suggestions;
  3. keep the person's species label and re-point it at the new frames that fit it: frames with a bird for a
     bird label, frames without one for Empty. If none fit, the old labelled frames are restored instead
     (nothing a person chose is lost) and the visit is reported - Check labels will show it after training.
Embeddings for the new frames are made by the running app's worker; train afterwards.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from . import frames as framelib
from .collector import rel
from .config import settings
from .db import DB
from .prelabel import LMStudio
from .species import NON_BIRD

NON_BIRD_NAMES = {n for n, _, _ in NON_BIRD}


def fits(label: str, s: dict | None) -> bool | None:
    """Does a frame suggestion fit the confirmed label? None = no suggestion."""
    if s is None:
        return None
    if label == "Empty":
        return not s.get("bird_present") and not s.get("other_animal")
    if label in NON_BIRD_NAMES and label != "Unknown bird":
        return bool(s.get("other_animal"))
    return bool(s.get("bird_present"))


def repick(db: DB, trace_id: str, lm: LMStudio | None, model: str | None, apply: bool) -> dict:
    v = db.one("SELECT * FROM visits WHERE trace_id=?", trace_id)
    clip = settings.image_dir / v["clip"]
    info: dict = {}
    if not apply:
        scores = framelib.score_frames(framelib.decode_small(clip))
        picks = framelib.choose(scores, settings.frames_per_visit)
        return {"trace_id": trace_id, "activity": round(max(scores), 4) if scores else 0,
                "new_frames": [p.t for p in picks],
                "old_frames": [r["t"] for r in db.q("SELECT t FROM frames WHERE trace_id=? AND kind='clip' AND rejected=0",
                                                    trace_id)]}
    picked = framelib.extract_best(clip, clip.parent, settings.frames_per_visit, info)
    new_ids = [db.add_frame(trace_id, "clip", rel(settings, f["path"]), rel(settings, f["thumb"]), f["t"], f["score"],
                            f["width"], f["height"], f.get("motion_box")) for f in picked]
    old = [r["id"] for r in db.q("SELECT id FROM frames WHERE trace_id=? AND kind='clip' AND rejected=0", trace_id)
           if r["id"] not in new_ids]
    with db.tx() as c:
        c.execute("UPDATE frames SET rejected=0 WHERE id IN (%s)" % ",".join("?" * len(new_ids)), new_ids)
        if old:
            c.execute("UPDATE frames SET rejected=1 WHERE id IN (%s)" % ",".join("?" * len(old)), old)
    db.set_visit(trace_id, activity=info.get("activity"))

    # suggestions for frames that have none yet
    sugg = {r["frame_id"]: dict(r) for r in db.q("SELECT * FROM suggestions WHERE trace_id=? AND source='vlm'", trace_id)}
    for fid in new_ids:
        if fid not in sugg and lm and model:
            f = db.one("SELECT path FROM frames WHERE id=?", fid)
            result, raw = lm.ask(model, (settings.image_dir / f["path"]).read_bytes())
            db.add_suggestion(trace_id, fid, "vlm", model, result or {}, raw[-4000:])
            sugg[fid] = {**(result or {}), "frame_id": fid}

    out = {"trace_id": trace_id, "activity": info.get("activity"), "new": len(new_ids), "rejected": len(old)}
    lab = db.one("SELECT * FROM labels WHERE trace_id=?", trace_id)
    if lab:
        good = [fid for fid in new_ids if fits(lab["species"], sugg.get(fid))]
        if good:
            frame_ids, out["label_frames"] = good, "new"
        else:   # nothing fits: put the person's own frames back rather than guess
            frame_ids = json.loads(lab["frame_ids"])
            with db.tx() as c:
                c.execute("UPDATE frames SET rejected=0 WHERE id IN (%s)" % ",".join("?" * len(frame_ids)), frame_ids)
            out["label_frames"] = "kept old (no new frame fits the label)"
        # keep the person's label, source and timestamps; only the frames move (per-frame species of dropped frames go)
        db.set_label_frames(trace_id, frame_ids, json.loads(lab["frame_species"] or "{}"), touch=False)
        out["label"] = lab["species"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    db = DB(settings.db_path)
    rows = db.q("SELECT trace_id FROM visits WHERE clip IS NOT NULL AND activity IS NULL ORDER BY ts")
    lm = LMStudio(settings)
    model = lm.pick_model() if args.apply else None
    print(f"{len(rows)} visit(s); LM Studio: {lm.status if args.apply else 'not used in a dry run'}")
    for r in rows:
        t = time.time()
        res = repick(db, r["trace_id"], lm, model, args.apply)
        print(json.dumps(res), f"{time.time() - t:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
