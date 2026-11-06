"""SQLite storage (keep it on a local disk; images can live on a NAS)."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .species import BIRDS, NON_BIRD

SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    trace_id TEXT PRIMARY KEY,
    serial TEXT, camera TEXT,
    ts REAL NOT NULL, time TEXT,
    vicohome_bird TEXT, vicohome_conf REAL, period REAL,
    snapshot TEXT, clip TEXT, clip_url TEXT,
    status TEXT NOT NULL DEFAULT 'new',      -- new | frames | prelabelled | failed
    error TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS visits_ts ON visits(ts);
CREATE INDEX IF NOT EXISTS visits_status ON visits(status);

CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY,
    trace_id TEXT NOT NULL REFERENCES visits(trace_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,                       -- snapshot | clip
    path TEXT NOT NULL, thumb TEXT,
    t REAL, score REAL, width INTEGER, height INTEGER,
    UNIQUE(trace_id, path)
);
CREATE INDEX IF NOT EXISTS frames_visit ON frames(trace_id);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY,
    trace_id TEXT NOT NULL REFERENCES visits(trace_id) ON DELETE CASCADE,
    frame_id INTEGER REFERENCES frames(id) ON DELETE CASCADE,
    source TEXT NOT NULL, model TEXT,
    bird_present INTEGER, count INTEGER,
    species TEXT, scientific TEXT, confidence REAL,
    other_animal TEXT, notes TEXT, raw TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS suggestions_visit ON suggestions(trace_id);

-- Only rows here are training data: every label was confirmed by a person.
CREATE TABLE IF NOT EXISTS labels (
    trace_id TEXT PRIMARY KEY REFERENCES visits(trace_id) ON DELETE CASCADE,
    species TEXT NOT NULL,
    count INTEGER,
    frame_ids TEXT NOT NULL,                  -- JSON list of the frames that show it
    source TEXT NOT NULL,                     -- confirmed | corrected
    created REAL NOT NULL, updated REAL NOT NULL
);

-- BioCLIP 2 image embeddings per frame: float32 array of shape (views, dim); views = full, left, centre, right.
CREATE TABLE IF NOT EXISTS embeddings (
    frame_id INTEGER PRIMARY KEY REFERENCES frames(id) ON DELETE CASCADE,
    embedder TEXT NOT NULL, views INTEGER NOT NULL, dim INTEGER NOT NULL,
    data BLOB NOT NULL, created REAL NOT NULL
);

-- Trained classifiers (v1: logistic regression on embeddings). Exactly one may be active.
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY,
    created REAL NOT NULL, embedder TEXT NOT NULL, kind TEXT NOT NULL,
    classes TEXT NOT NULL,                    -- JSON list
    n_visits INTEGER NOT NULL, n_frames INTEGER NOT NULL,
    metrics TEXT NOT NULL,                    -- JSON (cross-validation results)
    path TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS species (
    name TEXT PRIMARY KEY,
    scientific TEXT, kind TEXT NOT NULL,      -- bird | other
    note TEXT, active INTEGER NOT NULL DEFAULT 1
);
"""


class DB:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        with self.tx() as c:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(frames)")}
            if "rejected" not in cols:  # 0.3: a person can reject a frame (e.g. blurry) and grab another
                c.execute("ALTER TABLE frames ADD COLUMN rejected INTEGER NOT NULL DEFAULT 0")
            if "motion_box" not in cols:  # 0.9: where the frame changed (JSON [x1,y1,x2,y2] in 0..1)
                c.execute("ALTER TABLE frames ADD COLUMN motion_box TEXT")
            c.execute("""CREATE TABLE IF NOT EXISTS detections (
                frame_id INTEGER PRIMARY KEY REFERENCES frames(id) ON DELETE CASCADE,
                source TEXT NOT NULL, label TEXT, score REAL,
                x1 REAL, y1 REAL, x2 REAL, y2 REAL, created REAL NOT NULL)""")
            lcols = {r[1] for r in c.execute("PRAGMA table_info(labels)")}
            if "checked" not in lcols:   # 0.12: when a person last confirmed this label is right
                c.execute("ALTER TABLE labels ADD COLUMN checked REAL")
            # Cross-validated (out-of-fold) check of every confirmed visit, per trained model.
            c.execute("""CREATE TABLE IF NOT EXISTS label_checks (
                model_id INTEGER NOT NULL REFERENCES models(id) ON DELETE CASCADE,
                trace_id TEXT NOT NULL, label TEXT NOT NULL, predicted TEXT NOT NULL,
                p_label REAL NOT NULL, p_predicted REAL NOT NULL,
                PRIMARY KEY (model_id, trace_id))""")
            ecols = {r[1] for r in c.execute("PRAGMA table_info(embeddings)")}
            if "version" not in ecols:   # 0.9: version 2 adds a bird-crop view
                c.execute("ALTER TABLE embeddings ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
            c.execute("""CREATE TABLE IF NOT EXISTS prefs (
                key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL)""")
            vcols = {r[1] for r in c.execute("PRAGMA table_info(visits)")}
            for col, typ in (("rec_species", "TEXT"), ("rec_source", "TEXT"), ("rec_conf", "REAL"),
                             ("rec_guess", "TEXT"), ("rec_at", "REAL"),
                             ("activity", "REAL"), ("quiet", "INTEGER NOT NULL DEFAULT 0"),
                             ("excluded", "INTEGER NOT NULL DEFAULT 0"),
                             ("clip_cut", "REAL")):   # 0.15.1: seconds cut from the clip's start (NULL = not yet)
                if col not in vcols:  # 0.5: live recognition result published to Home Assistant
                    c.execute(f"ALTER TABLE visits ADD COLUMN {col} {typ}")
            if not c.execute("SELECT 1 FROM species LIMIT 1").fetchone():
                c.executemany("INSERT INTO species(name, scientific, kind, note) VALUES (?,?,?,?)",
                              [(n, s, "other", note) for n, s, note in NON_BIRD] +
                              [(n, s, "bird", "") for n, s in BIRDS])

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        c = self.conn()
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise

    def q(self, sql: str, *args: Any) -> list[sqlite3.Row]:
        return self.conn().execute(sql, args).fetchall()

    def one(self, sql: str, *args: Any) -> sqlite3.Row | None:
        return self.conn().execute(sql, args).fetchone()

    # ---- visits ---------------------------------------------------------
    def upsert_visit(self, rec: dict[str, Any]) -> bool:
        """Insert a visit from a bridge record; update fields that arrive later. True if new."""
        with self.tx() as c:
            new = c.execute("SELECT 1 FROM visits WHERE trace_id=?", (rec["trace_id"],)).fetchone() is None
            if new:
                c.execute("""INSERT INTO visits(trace_id, serial, camera, ts, time, vicohome_bird, vicohome_conf,
                             period, clip_url, created) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                          (rec["trace_id"], rec.get("serial"), rec.get("camera_name"), rec["timestamp"],
                           rec.get("time"), rec.get("bird"), rec.get("confidence"), rec.get("period"),
                           rec.get("clip_url"), time.time()))
            else:
                c.execute("""UPDATE visits SET clip_url=COALESCE(?, clip_url),
                             vicohome_bird=COALESCE(?, vicohome_bird), vicohome_conf=COALESCE(?, vicohome_conf)
                             WHERE trace_id=?""",
                          (rec.get("clip_url"), rec.get("bird"), rec.get("confidence"), rec["trace_id"]))
            return new

    def set_visit(self, trace_id: str, **fields: Any) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE visits SET {cols} WHERE trace_id=?", (*fields.values(), trace_id))

    def add_frame(self, trace_id: str, kind: str, path: str, thumb: str | None, t: float | None,
                  score: float | None, width: int | None, height: int | None,
                  motion_box: list[float] | None = None) -> int:
        with self.tx() as c:
            c.execute("""INSERT OR IGNORE INTO frames(trace_id, kind, path, thumb, t, score, width, height, motion_box)
                         VALUES (?,?,?,?,?,?,?,?,?)""", (trace_id, kind, path, thumb, t, score, width, height,
                                                       json.dumps(motion_box) if motion_box else None))
            return c.execute("SELECT id FROM frames WHERE trace_id=? AND path=?", (trace_id, path)).fetchone()[0]

    def add_suggestion(self, trace_id: str, frame_id: int | None, source: str, model: str,
                       result: dict[str, Any], raw: str) -> None:
        with self.tx() as c:
            c.execute("""INSERT INTO suggestions(trace_id, frame_id, source, model, bird_present, count, species,
                         scientific, confidence, other_animal, notes, raw, created) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (trace_id, frame_id, source, model,
                       None if result.get("bird_present") is None else int(bool(result.get("bird_present"))),
                       result.get("count"), result.get("species"), result.get("scientific_name"),
                       result.get("confidence"), result.get("other_animal"), result.get("notes"), raw, time.time()))

    def set_label(self, trace_id: str, species: str, frame_ids: list[int], count: int | None,
                  source: str) -> None:
        now = time.time()
        with self.tx() as c:   # a person just confirmed it, so it also counts as checked now
            c.execute("""INSERT INTO labels(trace_id, species, count, frame_ids, source, created, updated, checked)
                         VALUES (?,?,?,?,?,?,?,?)
                         ON CONFLICT(trace_id) DO UPDATE SET species=excluded.species, count=excluded.count,
                         frame_ids=excluded.frame_ids, source=excluded.source, updated=excluded.updated,
                         checked=excluded.checked""",
                      (trace_id, species, count, json.dumps(frame_ids), source, now, now, now))

    def delete_label(self, trace_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM labels WHERE trace_id=?", (trace_id,))
