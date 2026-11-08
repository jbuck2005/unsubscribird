"""Storage retention: delete the clips of visits a person confirmed as Empty, once they are old enough.

Only the clip.mp4 goes. Frames, thumbnails, labels and embeddings stay, so training, the Dataset page and Check
labels work as before. Visits that aren't labelled Empty by a person, or are excluded, are never touched.
A label changed in the last day is left alone too, so a slip of the key can still be undone with the clip intact.
"""

from __future__ import annotations

import logging
import threading
import time

LOG = logging.getLogger("wbs.retention")
DAY = 86400
LABEL_GRACE_S = DAY      # a label must be this old before its clip can go
MAX_PER_DAY = 150        # under the 200 deletions a night that a backup mirror (rsync --max-delete) may allow
INTERVAL_S = 3600


def due(db, days: int, now: float | None = None, limit: int = MAX_PER_DAY) -> list:
    """Visits whose clip can be deleted now, oldest first."""
    if days <= 0:
        return []
    now = now or time.time()
    return db.q("""SELECT v.trace_id, v.clip FROM visits v JOIN labels l USING(trace_id)
                   WHERE l.species='Empty' AND v.clip IS NOT NULL AND v.excluded=0
                     AND v.ts < ? AND l.updated < ?
                   ORDER BY v.ts LIMIT ?""", now - days * DAY, now - LABEL_GRACE_S, limit)


def remove_empty_clips(settings, db, now: float | None = None, per_day: int = MAX_PER_DAY) -> dict:
    """One pass, at most `per_day` deletions in any 24 h. Returns how many clips were deleted and the bytes freed."""
    now = now or time.time()
    recent = db.one("SELECT COUNT(*) n FROM visits WHERE clip_removed > ?", now - DAY)["n"]
    limit = max(0, per_day - recent)
    root = settings.image_dir.resolve()
    removed, freed, skipped = 0, 0, 0
    for r in (due(db, settings.empty_clip_days, now, limit) if limit else []):
        p = (settings.image_dir / r["clip"]).resolve()
        if p.name != "clip.mp4" or not p.is_relative_to(root):   # never follow an odd path out of the image folder
            LOG.warning("Visit %s: clip path %r looks wrong, left alone", r["trace_id"], r["clip"])
            skipped += 1
            continue
        try:
            size = p.stat().st_size
            p.unlink()
        except FileNotFoundError:
            size = 0
        except OSError as err:
            LOG.warning("Visit %s: couldn't delete the clip: %s", r["trace_id"], err)
            skipped += 1
            continue
        db.set_visit(r["trace_id"], clip=None, clip_removed=now)
        removed += 1
        freed += size
    if removed:
        LOG.info("Retention: deleted %d Empty clip(s), %.1f MB", removed, freed / 1e6)
    return {"removed": removed, "freed_bytes": freed, "skipped": skipped, "at": now}


class Retention:
    def __init__(self, settings, db) -> None:
        self.s, self.db = settings, db
        self.stop = threading.Event()
        self.last: dict | None = None

    def stats(self) -> dict:
        row = self.db.one("SELECT COUNT(*) n FROM visits WHERE clip_removed IS NOT NULL")
        return {"empty_clip_days": self.s.empty_clip_days, "clips_removed": row["n"],
                "due_now": len(due(self.db, self.s.empty_clip_days, limit=10_000)), "last_pass": self.last}

    def start(self) -> None:
        def loop():
            while not self.stop.is_set():
                try:   # reads the setting each time, so a change on the Settings page applies at the next pass
                    self.last = remove_empty_clips(self.s, self.db)
                except Exception:
                    LOG.exception("Retention pass failed")
                self.stop.wait(INTERVAL_S)
        threading.Thread(target=loop, name="retention", daemon=True).start()

