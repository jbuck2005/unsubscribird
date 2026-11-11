"""Trainer v1: logistic regression on BioCLIP 2 embeddings of user-confirmed frames (CPU, seconds).

* Training data = only frames listed in `labels` (a person confirmed them). Rejected frames never count.
* Each frame trains as its own species: the visit's label, or the per-frame species a person set on a mixed visit
  (a squirrel frame in a chickadee visit trains as Squirrel). Visit-level scores use the visit's main label.
* Evaluation is by VISIT: all frames of a visit stay on the same side of a split (they are near-duplicates),
  and a visit's prediction is the mean of its frames' probabilities.
* Classes need at least `min_visits` confirmed visits; others are listed as "not enough data yet".
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .db import DB
from .embed import EMBEDDER, EmbedWorker, frame_feature, from_blob, zero_shot

LOG = logging.getLogger("wbs.train")
MIN_VISITS = 3
C_GRID = (0.5, 2.0, 8.0)


def build_dataset(db: DB, worker: EmbedWorker) -> dict[str, Any]:
    names, text = worker.embedder.text_embeddings(worker.species_rows())
    non_bird = {r[0] for r in worker.species_rows() if r[2] == "other"}
    X, y, main, groups, frame_ids = [], [], [], [], []
    missing = 0
    for lab in db.q("SELECT l.* FROM labels l JOIN visits v USING(trace_id) WHERE v.excluded=0"):
        per_frame = json.loads(lab["frame_species"] or "{}")
        for fid in json.loads(lab["frame_ids"]):
            r = db.one("""SELECT e.* FROM embeddings e JOIN frames f ON f.id=e.frame_id
                          WHERE e.frame_id=? AND f.rejected=0""", fid)
            if not r:
                missing += 1
                continue
            views = from_blob(r["data"], r["views"], r["dim"])
            z = zero_shot(views, names, text, non_bird)
            X.append(frame_feature(views, z["view"]))
            y.append(per_frame.get(str(fid), lab["species"]))
            main.append(lab["species"])
            groups.append(lab["trace_id"])
            frame_ids.append(fid)
    return {"X": np.array(X, dtype=np.float32), "y": np.array(y), "main": np.array(main), "groups": np.array(groups),
            "frame_ids": frame_ids, "missing_embeddings": missing}


def visits_per_class(y: np.ndarray, groups: np.ndarray) -> Counter:
    """Visits each species appears in (a mixed visit counts for each of its species)."""
    return Counter(s for _, s in {(g, s) for g, s in zip(groups, y)})


def visit_labels(y: np.ndarray, main: np.ndarray, groups: np.ndarray, classes: list[str]) -> np.ndarray:
    """Per frame: its visit's label for visit-level scoring. The main label, or, if that species isn't trained
    (too few visits), the visit's most common frame species that is."""
    out = main.copy()
    for g in np.unique(groups):
        m = groups == g
        if main[m][0] not in classes:
            trained = [s for s in y[m] if s in classes] or list(y[m])
            out[m] = Counter(trained).most_common(1)[0][0]
    return out


def visit_level(probs: np.ndarray, groups: np.ndarray, vlab: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
    visits = list(dict.fromkeys(groups))
    vp = np.array([probs[groups == g].mean(axis=0) for g in visits])
    vy = np.array([vlab[groups == g][0] for g in visits])
    return visits, vp, vy


def calibrate(p: np.ndarray, T: float) -> np.ndarray:
    """Temperature scaling of probabilities (T < 1 sharpens, T > 1 softens)."""
    logits = np.log(np.clip(p, 1e-9, 1.0)) / T
    logits -= logits.max(axis=-1, keepdims=True)
    e = np.exp(logits)
    return e / e.sum(axis=-1, keepdims=True)


def fit_temperature(vp: np.ndarray, vy: np.ndarray, classes: list[str]) -> float:
    """Pick T that best explains the out-of-fold VISIT predictions (lowest negative log-likelihood).

    A strongly regularised model on little data is usually right but reports ~50%; this restores honest
    confidence so a threshold like 75% means something."""
    idx = np.array([classes.index(c) for c in vy])
    best_T, best_nll = 1.0, float("inf")
    for T in np.geomspace(0.05, 3.0, 80):
        p = calibrate(vp, T)[np.arange(len(idx)), idx]
        nll = float(-np.log(np.clip(p, 1e-9, 1.0)).mean())
        if nll < best_nll:
            best_T, best_nll = float(T), nll
    return round(best_T, 4)


def coverage(vp: np.ndarray, vy: np.ndarray, classes: list[str], threshold: float) -> dict[str, Any]:
    """Of the visits the model would decide on its own at this threshold: how many, and how often right."""
    conf = vp.max(axis=1)
    pred = np.array(classes)[vp.argmax(axis=1)]
    sel = conf >= threshold
    return {"threshold": threshold, "decided": round(float(sel.mean()), 3),
            "accuracy": round(float((pred[sel] == vy[sel]).mean()), 3) if sel.any() else None}


def cross_validate(X, y, groups, classes: list[str], C: float, seed: int = 0) -> dict[str, Any] | None:
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedGroupKFold

    per_class = visits_per_class(y, groups)
    n_splits = min(5, min(per_class[c] for c in classes))
    if n_splits < 2:
        return None
    oof = np.zeros((len(y), len(classes)))
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr, te in cv.split(X, y, groups):
        clf = LogisticRegression(C=C, max_iter=5000, class_weight="balanced")
        clf.fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])
        oof[np.ix_(te, [classes.index(c) for c in clf.classes_])] = p
    return {"oof": oof, "n_splits": n_splits}


def metrics_from(oof: np.ndarray, X, y, groups, classes: list[str], vlab: np.ndarray | None = None) -> dict[str, Any]:
    frame_pred = np.array(classes)[oof.argmax(axis=1)]
    visits, vp, vy = visit_level(oof, groups, y if vlab is None else vlab)
    vpred = np.array(classes)[vp.argmax(axis=1)]
    per_class = {}
    for c in classes:
        tp = int(((vpred == c) & (vy == c)).sum())
        fp = int(((vpred == c) & (vy != c)).sum())
        fn = int(((vpred != c) & (vy == c)).sum())
        per_class[c] = {"visits": int((vy == c).sum()),
                        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
                        "recall": round(tp / (tp + fn), 3) if tp + fn else None}
    confusion = [[int(((vy == a) & (vpred == b)).sum()) for b in classes] for a in classes]
    suspects = [{"trace_id": v, "label": l, "predicted": p, "confidence": round(float(pp.max()), 3)}
                for v, l, p, pp in zip(visits, vy, vpred, vp) if l != p and pp.max() >= 0.7]
    return {"frame_accuracy": round(float((frame_pred == y).mean()), 3),
            "visit_accuracy": round(float((vpred == vy).mean()), 3),
            "visits": len(visits), "per_class": per_class, "confusion": confusion,
            "suspect_labels": sorted(suspects, key=lambda s: -s["confidence"])[:30]}


def baselines(db: DB, visits: list[str], labels: dict[str, str]) -> dict[str, Any]:
    """How the zero-shot BioCLIP and LM Studio suggestions did on the same visits."""
    from .prelabel import consensus
    out = {}
    for source in ("bioclip", "vlm"):
        right = total = 0
        for v in visits:
            rows = [dict(r) for r in db.q("SELECT * FROM suggestions WHERE trace_id=? AND source=?", v, source)]
            if not rows:
                continue
            guess = rows[-1]["species"] if source == "bioclip" else (consensus(rows) or {}).get("species")
            total += 1
            right += int((guess or "").lower() == labels[v].lower())
        out[source] = {"visit_accuracy": round(right / total, 3) if total else None, "visits": total}
    return out


class Trainer:
    def __init__(self, db: DB, worker: EmbedWorker, model_dir: Path) -> None:
        self.db, self.worker, self.model_dir = db, worker, model_dir
        self.status: dict[str, Any] = {"state": "idle", "message": "", "started": None, "finished": None}
        self._lock = threading.Lock()
        self._cache: tuple[int, Any] | None = None
        self.after_predict = None       # e.g. refresh Home Assistant
        worker.predictor = self.predict_visit

    # ---- training ---------------------------------------------------------------
    def start(self) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        self.status = {"state": "running", "message": "starting", "started": time.time(), "finished": None}
        threading.Thread(target=self._run, name="train", daemon=True).start()
        return True

    def _run(self) -> None:
        try:
            self.status.update(self.train())
            self.status["state"] = "done"
        except Exception as err:
            LOG.exception("Training failed")
            self.status.update(state="failed", message=str(err)[:300])
        finally:
            self.status["finished"] = time.time()
            self._lock.release()

    def train(self, min_visits: int = MIN_VISITS, activate: bool = True, kind: str = "logreg",
              extra_metrics: dict | None = None) -> dict[str, Any]:
        import joblib
        from sklearn.linear_model import LogisticRegression

        self.status["message"] = "building dataset"
        ds = build_dataset(self.db, self.worker)
        X, y, groups, main = ds["X"], ds["y"], ds["groups"], ds["main"]
        if not len(y):
            raise ValueError("no confirmed frames with embeddings yet")
        vcount = visits_per_class(y, groups)
        classes = sorted(c for c, n in vcount.items() if n >= min_visits)
        too_few = {c: n for c, n in vcount.items() if n < min_visits}
        if len(classes) < 2:
            raise ValueError(f"need at least 2 species with {min_visits}+ confirmed visits; have "
                             + ", ".join(f"{c} {n}" for c, n in vcount.most_common()))
        keep = np.isin(y, classes)
        X, y, groups, main = X[keep], y[keep], groups[keep], main[keep]
        vlab = visit_labels(y, main, groups, classes)

        self.status["message"] = "cross-validating"
        best = None
        for C in C_GRID:
            cv = cross_validate(X, y, groups, classes, C)
            if cv is None:
                break
            m = metrics_from(cv["oof"], X, y, groups, classes, vlab)
            if best is None or m["visit_accuracy"] > best[1]["visit_accuracy"]:
                best = (C, m, cv["n_splits"], cv["oof"])
        C = best[0] if best else 2.0
        metrics: dict[str, Any] = best[1] if best else {"note": "too few visits to cross-validate"}
        T = 1.0
        checks: list[tuple] = []
        if best:
            vids, vp, vy = visit_level(best[3], groups, vlab)
            T = fit_temperature(vp, vy, classes)
            cal = calibrate(vp, T)
            for vid, p, lab in zip(vids, cal, vy):
                top = int(np.argmax(p))
                checks.append((vid, str(lab), classes[top], float(p[classes.index(lab)]), float(p[top])))
            metrics["calibration"] = {"temperature": T,
                                      "raw": [coverage(vp, vy, classes, t) for t in (0.6, 0.75, 0.9)],
                                      "calibrated": [coverage(cal, vy, classes, t) for t in (0.6, 0.75, 0.9)]}
        metrics.update({"C": C, "cv_folds": best[2] if best else 0, "too_few": too_few,
                        "missing_embeddings": ds["missing_embeddings"], **(extra_metrics or {})})
        visits = list(dict.fromkeys(groups))
        labels = {g: vlab[groups == g][0] for g in visits}
        metrics["baselines"] = baselines(self.db, visits, labels)

        self.status["message"] = "fitting final model"
        clf = LogisticRegression(C=C, max_iter=5000, class_weight="balanced").fit(X, y)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        with self.db.tx() as c:
            cur = c.execute("""INSERT INTO models(created, embedder, kind, classes, n_visits, n_frames, metrics, path)
                               VALUES (?,?,?,?,?,?,?,?)""",
                            (time.time(), EMBEDDER, kind, json.dumps(list(clf.classes_)), len(visits), len(y),
                             json.dumps(metrics), ""))
            mid = cur.lastrowid
        path = self.model_dir / f"model_{mid:04d}.joblib"
        joblib.dump({"clf": clf, "classes": list(clf.classes_), "embedder": EMBEDDER, "feature": "bestview+full",
                     "temperature": T}, path)
        with self.db.tx() as c:
            c.execute("UPDATE models SET path=? WHERE id=?", (str(path), mid))
            c.executemany("""INSERT OR REPLACE INTO label_checks(model_id, trace_id, label, predicted, p_label, p_predicted)
                             VALUES (?,?,?,?,?,?)""", [(mid, *ch) for ch in checks])
        if not activate:
            LOG.info("Candidate model v%d trained (not activated)", mid)
            return {"message": f"candidate v{mid} trained", "model_id": mid, "metrics": metrics}
        self.activate(mid)
        LOG.info("Model v%d: %d classes, %d visits, CV visit accuracy %s", mid, len(classes), len(visits),
                 metrics.get("visit_accuracy"))
        n = self.after_activate()
        return {"message": f"model v{mid} trained; predicted {n} visits", "model_id": mid}

    def activate(self, mid: int) -> None:
        with self.db.tx() as c:
            c.execute("UPDATE models SET active=(id=?)", (mid,))
        self._cache = None

    def after_activate(self) -> int:
        self.status["message"] = "predicting unconfirmed visits"
        n = self.predict_all()
        if self.after_predict:
            self.after_predict()
        return n

    # ---- nightly auto-retrain -----------------------------------------------------
    def fresh_accuracy(self, model_row) -> tuple[float | None, int]:
        """Accuracy of a model on visits confirmed AFTER it was trained (it never saw them)."""
        import joblib
        bundle = joblib.load(model_row["path"])
        right = total = 0
        for lab in self.db.q("""SELECT l.* FROM labels l JOIN visits v USING(trace_id)
                                 WHERE v.excluded=0 AND l.updated > ?""", model_row["created"]):
            got = self.visit_probs(bundle, lab["trace_id"])
            if got is None:
                continue
            classes, p = got
            total += 1
            right += int(classes[int(np.argmax(p))] == lab["species"])
        return (round(right / total, 3) if total else None), total

    def auto_retrain(self, min_new: int, tolerance: float = 0.02) -> dict[str, Any]:
        """Train a candidate; activate it only if it is not worse than the active model on fresh data."""
        active = self.db.one("SELECT * FROM models WHERE active=1")
        new = self.db.one("""SELECT COUNT(*) n FROM labels l JOIN visits v USING(trace_id)
                             WHERE v.excluded=0 AND l.updated > ?""", active["created"] if active else 0)["n"]
        if new < min_new:
            return {"decision": "skipped", "reason": f"{new} new confirmed visits (< {min_new})"}
        fresh, n_fresh = self.fresh_accuracy(active) if active else (None, 0)
        cand = self.train(activate=False, kind="auto")
        cv = cand["metrics"].get("visit_accuracy")
        if not active:
            ok, why = True, "no active model"
        elif cv is None:
            ok, why = False, "candidate could not be cross-validated"
        elif fresh is not None and n_fresh >= 5:
            ok = cv >= fresh - tolerance
            why = f"candidate CV {cv:.1%} vs active v{active['id']} on {n_fresh} new visits {fresh:.1%}"
        else:
            old = json.loads(active["metrics"]).get("visit_accuracy") or 0
            ok = cv >= old - tolerance
            why = f"candidate CV {cv:.1%} vs active v{active['id']} CV {old:.1%} (too few new visits for a fresh test)"
        decision = {"decision": "activated" if ok else "kept active", "reason": why, "new_visits": new,
                    "at": time.time()}
        m = json.loads(self.db.one("SELECT metrics FROM models WHERE id=?", cand["model_id"])["metrics"])
        m["auto"] = decision
        with self.db.tx() as c:
            c.execute("UPDATE models SET metrics=? WHERE id=?", (json.dumps(m), cand["model_id"]))
        if ok:
            self.activate(cand["model_id"])
            self.after_activate()
        LOG.info("Auto-retrain: candidate v%d %s (%s)", cand["model_id"], decision["decision"], why)
        return {**decision, "model_id": cand["model_id"]}

    def retrain_due(self, settings, now: float | None = None) -> bool:
        """At the retrain hour, once `auto_train_days` have passed since the last model was trained. Counted from
        the models table, so a restart doesn't reset it; half a day of slack keeps it at the same hour each time."""
        now = time.time() if now is None else now
        if not settings.auto_train or time.localtime(now).tm_hour != settings.auto_train_hour:
            return False
        last = self.db.one("SELECT MAX(created) t FROM models")["t"]
        return last is None or now - last >= (max(1, settings.auto_train_days) - 0.5) * 86400

    def start_scheduler(self, settings) -> None:
        """Automatic retrain. Reads the settings each time round, so changes on the Settings page apply at once."""
        def loop():
            last_day = None
            while True:
                now = time.localtime()
                if (last_day != now.tm_yday and self.retrain_due(settings)
                        and self._lock.acquire(blocking=False)):
                    last_day = now.tm_yday
                    try:
                        self.status.update(state="running", message="nightly auto-retrain", started=time.time())
                        self.status.update(self.auto_retrain(settings.auto_train_min_new), state="done", finished=time.time())
                    except Exception as err:
                        LOG.exception("Auto-retrain failed")
                        self.status.update(state="failed", message=str(err)[:300], finished=time.time())
                    finally:
                        self._lock.release()
                time.sleep(300)
        threading.Thread(target=loop, name="auto-train", daemon=True).start()

    # ---- prediction -------------------------------------------------------------
    def active(self):
        row = self.db.one("SELECT * FROM models WHERE active=1")
        if not row:
            return None, None
        if not self._cache or self._cache[0] != row["id"]:
            import joblib
            self._cache = (row["id"], joblib.load(row["path"]))
        return row, self._cache[1]

    def visit_probs(self, bundle, trace_id: str) -> tuple[list[str], np.ndarray] | None:
        frames = self.worker.visit_views(trace_id)
        if not frames:
            return None
        names, text = self.worker.embedder.text_embeddings(self.worker.species_rows())
        non_bird = {r[0] for r in self.worker.species_rows() if r[2] == "other"}
        X = np.array([frame_feature(v, zero_shot(v, names, text, non_bird)["view"]) for _, v in frames])
        p = calibrate(bundle["clf"].predict_proba(X).mean(axis=0), bundle.get("temperature", 1.0))
        return bundle["classes"], p

    def predict_visit(self, trace_id: str) -> dict[str, Any] | None:
        row, bundle = self.active()
        if not row:
            return None
        got = self.visit_probs(bundle, trace_id)
        if got is None:
            return None
        classes, p = got
        non_bird = {r[0] for r in self.worker.species_rows() if r[2] == "other"}
        top = int(np.argmax(p))
        result = {"bird_present": classes[top] not in non_bird, "species": classes[top],
                  "confidence": round(float(p[top]), 3),
                  "notes": f"model v{row['id']}: " + ", ".join(f"{classes[i]} {p[i]:.0%}" for i in np.argsort(-p)[:3])}
        with self.db.tx() as c:
            c.execute("DELETE FROM suggestions WHERE trace_id=? AND source='model'", (trace_id,))
        self.db.add_suggestion(trace_id, None, "model", f"v{row['id']}", result, "")
        return result

    def predict_all(self) -> int:
        n = 0
        for v in self.db.q("SELECT trace_id FROM visits WHERE status IN ('frames','prelabelled')"):
            if self.predict_visit(v["trace_id"]):
                n += 1
        return n
