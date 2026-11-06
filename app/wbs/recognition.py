"""Live recognition: decide what each new visit was and publish it to Home Assistant over MQTT.

Decision per visit (thresholds in config):
  1. the active trained model, if it is confident enough (it only knows species with 3+ confirmed visits);
  2. otherwise the LM Studio suggestion (consensus over frames), if confident enough (covers new species);
  3. otherwise "Uncertain" (best guess kept as an attribute); such visits go to the top of the review queue.
A visit is decided once the model has seen it AND LM Studio has (or `ha_wait_vlm_s` passed without it).
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable

from .config import Settings
from .db import DB
from .prelabel import consensus
from .species import NON_BIRD

LOG = logging.getLogger("wbs.recognition")
NON_BIRD_NAMES = {n for n, _, _ in NON_BIRD}
UNCERTAIN = "Uncertain"
GALLERY_DAYS = 7
# Timeline colours: each species gets the next colour in order of its first sighting of the day.
DOTS = ["🔵", "🟢", "🟠", "🟣", "🟡", "🔴", "🟤", "⚫", "⚪"]


def day_colours(species_oldest_first: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sp in species_oldest_first:
        if sp == UNCERTAIN:
            out.setdefault(sp, "❔")
        elif sp not in out:
            out[sp] = DOTS[len([k for k in out if k != UNCERTAIN]) % len(DOTS)]
    return out
GALLERY_MAX = 12


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
FRESH_S = 15 * 60


def event_type(species: str) -> str:
    if species == UNCERTAIN:
        return "uncertain"
    if species == "Empty":
        return "empty"
    if species in NON_BIRD_NAMES and species != "Unknown bird":
        return "other_animal"
    return "bird"


def decide(model: dict | None, vlm: dict | None, model_min: float, vlm_min: float,
           model_classes: list[str] | None = None) -> dict[str, Any]:
    """model/vlm: {'species', 'confidence'} or None -> {'species', 'source', 'confidence', 'guess'}."""
    # The model can only answer with species it was trained on; if LM Studio is confident about one it has
    # never learned (e.g. the first cardinal), trust LM Studio rather than the model's forced choice.
    if (vlm and model_classes is not None and (vlm.get("confidence") or 0) >= vlm_min
            and vlm.get("species") not in model_classes):
        return {"species": vlm["species"], "source": "lmstudio", "confidence": vlm["confidence"], "guess": None}
    if model and (model.get("confidence") or 0) >= model_min:
        return {"species": model["species"], "source": "model", "confidence": model["confidence"], "guess": None}
    if vlm and (vlm.get("confidence") or 0) >= vlm_min:
        return {"species": vlm["species"], "source": "lmstudio", "confidence": vlm["confidence"], "guess": None}
    candidates = [c for c in (model, vlm) if c and c.get("species")]
    best = max(candidates, key=lambda c: c.get("confidence") or 0) if candidates else None
    return {"species": UNCERTAIN, "source": "uncertain", "confidence": (best or {}).get("confidence"),
            "guess": (best or {}).get("species")}


class Recognizer:
    def __init__(self, settings: Settings, db: DB, publish: Callable[[str, Any, bool], None],
                 canonical: Callable[[str | None], str | None] = lambda n: n) -> None:
        self.s, self.db, self.publish, self.canonical = settings, db, publish, canonical
        self.stop = threading.Event()
        self.stats: dict[str, Any] = {"published": 0, "last": None, "last_error": ""}
        self._gallery_sent: dict[str, str] = {}   # species slug -> trace id whose photo HA has
        self._sighting_types_sent: set[str] = set()

    # ---- topics / discovery ---------------------------------------------------------
    def t(self, sub: str) -> str:
        return f"{self.s.ha_topic}/{sub}"

    def discovery(self) -> list[tuple[str, dict]]:
        dev = {"identifiers": [self.s.ha_id], "name": self.s.site_name, "manufacturer": "jbuck2005",
               "model": "unsubscribird", "configuration_url": self.s.public_url}
        avail = {"availability_topic": self.t("status")}
        base = {"device": dev, **avail, "has_entity_name": True,
                "origin": {"name": "unsubscribird", "url": "https://github.com/jbuck2005/unsubscribird"}}
        p = self.s.ha_discovery_prefix

        def cfg(component, key, body):
            return (f"{p}/{component}/{self.s.ha_id}/{key}/config",
                    {**base, **body, "unique_id": f"{self.s.ha_id}_{key}",
                     "default_entity_id": f"{component}.{self.s.ha_id}_{key}"})

        return [
            cfg("sensor", "last_bird", {"name": "Last bird", "icon": "mdi:bird", "state_topic": self.t("last_bird"),
                                        "value_template": "{{ value_json.species }}",
                                        "json_attributes_topic": self.t("last_bird")}),
            cfg("sensor", "last_bird_confidence", {"name": "Last bird confidence", "icon": "mdi:percent",
                                                   "unit_of_measurement": "%", "state_topic": self.t("last_bird"),
                                                   "value_template": "{{ (value_json.confidence * 100) | round(0) }}"}),
            cfg("sensor", "last_visit", {"name": "Last visit", "icon": "mdi:eye", "state_topic": self.t("last_visit"),
                                         "value_template": "{{ value_json.species }}",
                                         "json_attributes_topic": self.t("last_visit")}),
            cfg("sensor", "species_today", {"name": "Species today", "icon": "mdi:format-list-bulleted",
                                            "state_topic": self.t("today"), "unit_of_measurement": "species",
                                            "value_template": "{{ value_json.species }}",
                                            "json_attributes_topic": self.t("today")}),
            cfg("sensor", "bird_visits_today", {"name": "Bird visits today", "icon": "mdi:counter",
                                                "state_topic": self.t("today"), "unit_of_measurement": "visits",
                                                "value_template": "{{ value_json.bird_visits }}"}),
            cfg("image", "last_bird_photo", {"name": "Last bird photo", "image_topic": self.t("image"),
                                             "content_type": "image/jpeg"}),
            cfg("event", "visit", {"name": "Visit", "state_topic": self.t("event"),
                                   "event_types": ["bird", "empty", "other_animal", "uncertain"]}),
            self.sighting_config(),
            cfg("sensor", "species_gallery", {"name": "Species gallery", "icon": "mdi:view-gallery",
                                              "state_topic": self.t("gallery"), "unit_of_measurement": "species",
                                              "value_template": "{{ value_json.count }}",
                                              "json_attributes_topic": self.t("gallery")}),
        ]

    def sighting_types(self) -> list[str]:
        names = [r["name"] for r in self.db.q("SELECT name FROM species WHERE active=1 ORDER BY name")
                 if r["name"] not in ("Empty",)]
        extra = [r["s"] for r in self.db.q("SELECT DISTINCT rec_species s FROM visits WHERE rec_species IS NOT NULL")
                 if r["s"] not in names and r["s"] not in ("Empty", UNCERTAIN)]
        return names + sorted(extra)

    def sighting_config(self) -> tuple[str, dict]:
        """Event whose type is the SPECIES (for the logbook timeline). Only real sightings fire it, and it has
        no availability topic, so app restarts don't add 'became unavailable' lines."""
        dev = {"identifiers": [self.s.ha_id], "name": self.s.site_name}
        return (f"{self.s.ha_discovery_prefix}/event/{self.s.ha_id}/sighting/config",
                {"device": dev, "has_entity_name": True, "name": "Sighting", "icon": "mdi:binoculars",
                 "unique_id": f"{self.s.ha_id}_sighting", "default_entity_id": f"event.{self.s.ha_id}_sighting",
                 "state_topic": self.t("sighting"),
                 "event_types": self.sighting_types()})

    def species_image_config(self, name: str) -> tuple[str, dict]:
        topic, body = [c for c in self.discovery() if c[0].endswith("/last_bird_photo/config")][0]
        key = f"species_{slug(name)}"
        return (topic.replace("/last_bird_photo/", f"/{key}/"),
                {**body, "name": f"{name} photo", "unique_id": f"{self.s.ha_id}_{key}", "default_entity_id": f"image.{self.s.ha_id}_{key}",
                 "image_topic": self.t(f"species/{slug(name)}/image")})

    def publish_discovery(self) -> None:
        for topic, body in self.discovery():
            self.publish(topic, json.dumps(body), True)
        self._gallery_sent = {}            # HA may have restarted: re-send species photos too
        self._sighting_types_sent = set(self.sighting_config()[1]["event_types"])
        self.publish(self.t("status"), "online", True)
        self.publish_today()

    # ---- deciding a visit -----------------------------------------------------------
    def decide_visit(self, trace_id: str) -> tuple[dict, dict | None, dict | None]:
        label = self.db.one("SELECT species FROM labels WHERE trace_id=?", trace_id)
        model, vlm = self.inputs(trace_id)
        if label:   # a person confirmed it: that wins
            return {"species": label["species"], "source": "confirmed", "confidence": 1.0, "guess": None}, model, vlm
        v = self.db.one("SELECT quiet FROM visits WHERE trace_id=?", trace_id)
        if v and v["quiet"]:   # nothing moved in the clip
            return {"species": "Empty", "source": "motion", "confidence": 0.9, "guess": None}, model, vlm
        row = self.db.one("SELECT classes FROM models WHERE active=1")
        classes = json.loads(row["classes"]) if row else None
        return decide(model, vlm, self.s.ha_model_confidence, self.s.ha_vlm_confidence, classes), model, vlm

    def inputs(self, trace_id: str) -> tuple[dict | None, dict | None]:
        model = self.db.one("SELECT * FROM suggestions WHERE trace_id=? AND source='model' ORDER BY id DESC",
                            trace_id)
        active = {r["frame_id"] for r in self.db.q("SELECT id frame_id FROM frames WHERE trace_id=? AND rejected=0",
                                                   trace_id)}
        vlm_rows = [dict(r) for r in self.db.q("SELECT * FROM suggestions WHERE trace_id=? AND source='vlm'", trace_id)
                    if r["frame_id"] is None or r["frame_id"] in active]
        for r in vlm_rows:
            r["species"] = self.canonical(r["species"])
        vlm = consensus(vlm_rows)
        m = {"species": model["species"], "confidence": model["confidence"], "model": model["model"]} if model else None
        return m, vlm

    def ready(self, v, has_model: bool) -> bool:
        embedded = self.db.one("""SELECT COUNT(*) n FROM frames f LEFT JOIN embeddings e ON e.frame_id=f.id
                                  WHERE f.trace_id=? AND f.rejected=0 AND e.frame_id IS NULL""", v["trace_id"])["n"] == 0
        model_done = (not has_model) or v["quiet"] or (embedded and self.db.one(
            "SELECT 1 FROM suggestions WHERE trace_id=? AND source='model'", v["trace_id"]) is not None)
        vlm_done = v["status"] == "prelabelled"
        waited = time.time() - v["created"] > self.s.ha_wait_vlm_s
        return model_done and (vlm_done or waited)

    def run_once(self) -> int:
        has_model = self.db.one("SELECT 1 FROM models WHERE active=1") is not None
        rows = self.db.q("""SELECT * FROM visits WHERE rec_at IS NULL AND status IN ('frames','prelabelled')
                            AND ts > ? ORDER BY ts""", time.time() - self.s.ha_max_age_h * 3600)
        n = 0
        for v in rows:
            if self.ready(v, has_model):
                self.recognize(v)
                n += 1
        return n

    def recognize(self, v) -> dict[str, Any]:
        d, model, vlm = self.decide_visit(v["trace_id"])
        self.db.set_visit(v["trace_id"], rec_species=d["species"], rec_source=d["source"],
                          rec_conf=d["confidence"], rec_guess=d["guess"], rec_at=time.time())
        payload = self.payload(v, d, model, vlm)
        self.publish(self.t("last_visit"), json.dumps(payload), True)
        if event_type(d["species"]) == "bird" and d["species"] != "Unknown bird":
            self.publish(self.t("last_bird"), json.dumps(payload), True)
            frame = self.best_frame(v["trace_id"])
            if frame:
                self.publish(self.t("image"), (self.s.image_dir / frame["path"]).read_bytes(), True)
        self.publish_today()
        # The event goes out LAST so an automation reacting to it already sees the new photo and counts.
        # Only fresh visits fire it (a backlog after a restart must not trigger automations).
        if time.time() - v["ts"] < FRESH_S:
            self.publish(self.t("event"), json.dumps({"event_type": event_type(d["species"]),
                                                      **self.firsts(v, d["species"]), **payload}), False)
            if d["species"] not in ("Empty", UNCERTAIN):
                topic, cfg = self.sighting_config()
                if d["species"] not in self._sighting_types_sent:
                    self.publish(topic, json.dumps(cfg), True)          # new species: extend event_types first
                    self._sighting_types_sent = set(cfg["event_types"])
                self.publish(self.t("sighting"), json.dumps({"event_type": d["species"], **payload}), False)
        self.stats["published"] += 1
        self.stats["last"] = {"trace_id": v["trace_id"], **d}
        LOG.info("Visit %s recognised as %s (%s, %s)", v["trace_id"], d["species"], d["source"], d["confidence"])
        return d

    def refresh(self, trace_id: str | None = None, since_h: float | None = None) -> int:
        """Re-decide already published visits (after a label change or a new model) WITHOUT firing events,
        then re-publish the current Last visit / Last bird / today."""
        if trace_id:
            rows = self.db.q("SELECT * FROM visits WHERE trace_id=? AND rec_at IS NOT NULL", trace_id)
        else:
            rows = self.db.q("SELECT * FROM visits WHERE rec_at IS NOT NULL AND ts > ?",
                             time.time() - (since_h or self.s.ha_max_age_h) * 3600)
        for v in rows:
            d, _, _ = self.decide_visit(v["trace_id"])
            self.db.set_visit(v["trace_id"], rec_species=d["species"], rec_source=d["source"],
                              rec_conf=d["confidence"], rec_guess=d["guess"])
        if rows:
            self.publish_current()
        return len(rows)

    def publish_current(self) -> None:
        last = self.db.one("SELECT * FROM visits WHERE rec_at IS NOT NULL ORDER BY ts DESC LIMIT 1")
        if last:
            d, model, vlm = self.decide_visit(last["trace_id"])
            self.publish(self.t("last_visit"), json.dumps(self.payload(last, d, model, vlm)), True)
        for v in self.db.q("SELECT * FROM visits WHERE rec_at IS NOT NULL ORDER BY ts DESC LIMIT 200"):
            if event_type(v["rec_species"]) == "bird" and v["rec_species"] != "Unknown bird":
                d, model, vlm = self.decide_visit(v["trace_id"])
                self.publish(self.t("last_bird"), json.dumps(self.payload(v, d, model, vlm)), True)
                frame = self.best_frame(v["trace_id"])
                if frame:
                    self.publish(self.t("image"), (self.s.image_dir / frame["path"]).read_bytes(), True)
                break
        self.publish_today()

    def payload(self, v, d, model, vlm) -> dict[str, Any]:
        return {"species": d["species"], "confidence": d["confidence"], "source": d["source"], "guess": d["guess"],
                "time": v["time"] or datetime.fromtimestamp(v["ts"]).astimezone().isoformat(),
                "trace_id": v["trace_id"], "review_url": f"{self.s.public_url}/admin?visit={v['trace_id']}",
                "model": model, "lmstudio": vlm and {k: vlm[k] for k in ("species", "confidence")},
                "vicohome": v["vicohome_bird"]}

    def firsts(self, v, species: str) -> dict[str, bool]:
        """Is this the first visit of this species today / ever (by recognised result or confirmed label)?"""
        if event_type(species) != "bird" or species == "Unknown bird":
            return {"first_today": False, "first_ever": False}
        start = datetime.fromtimestamp(v["ts"]).astimezone().replace(hour=0, minute=0, second=0,
                                                                      microsecond=0).timestamp()
        earlier = """SELECT 1 FROM visits v LEFT JOIN labels l USING(trace_id)
                     WHERE v.trace_id != ? AND v.ts < ? AND v.ts >= ? AND (v.rec_species = ? OR l.species = ?) LIMIT 1"""
        today = self.db.one(earlier, v["trace_id"], v["ts"], start, species, species) is None
        ever = today and self.db.one(earlier, v["trace_id"], v["ts"], 0, species, species) is None
        return {"first_today": today, "first_ever": ever}

    def best_frame(self, trace_id: str):
        return self.db.one("""SELECT * FROM frames WHERE trace_id=? AND rejected=0
                              ORDER BY (kind='clip') DESC, score DESC LIMIT 1""", trace_id)

    def today_summary(self) -> dict[str, Any]:
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        rows = self.db.q("SELECT rec_species s, COUNT(*) n FROM visits WHERE rec_at IS NOT NULL AND ts >= ? "
                         "GROUP BY rec_species", start)
        counts = {r["s"]: r["n"] for r in rows}
        birds = {s: n for s, n in counts.items() if event_type(s) == "bird" and s != "Unknown bird"}
        recent = [{"time": r["time"] or datetime.fromtimestamp(r["ts"]).astimezone().isoformat(),
                   "species": r["rec_species"], "confidence": r["rec_conf"], "source": r["rec_source"],
                   "guess": r["rec_guess"], "trace_id": r["trace_id"], "clip_url": r["clip_url"]}
                  for r in self.db.q("""SELECT * FROM visits WHERE rec_at IS NOT NULL
                                        ORDER BY ts DESC LIMIT 10""")]
        return {"species": len(birds), "bird_visits": sum(n for s, n in counts.items() if event_type(s) == "bird"),
                "recent": recent, "review_base": f"{self.s.public_url}/admin?visit=",
                "sightings": self.sightings(start),
                "by_species": dict(sorted(birds.items(), key=lambda kv: -kv[1])),
                "empty": counts.get("Empty", 0), "uncertain": counts.get(UNCERTAIN, 0),
                "other_animals": sum(n for s, n in counts.items() if event_type(s) == "other_animal")}

    def sightings(self, start: float) -> list[dict[str, Any]]:
        """Today's non-empty visits, newest first, each with its species' colour for the day."""
        rows = self.db.q("""SELECT * FROM visits WHERE rec_at IS NOT NULL AND ts >= ? AND rec_species != 'Empty'
                            ORDER BY ts""", start)
        colours = day_colours([r["rec_species"] for r in rows])
        return [{"time": r["time"] or datetime.fromtimestamp(r["ts"]).astimezone().isoformat(),
                 "species": r["rec_species"], "dot": colours[r["rec_species"]], "confidence": r["rec_conf"],
                 "source": r["rec_source"], "guess": r["rec_guess"], "trace_id": r["trace_id"], "clip_url": r["clip_url"]}
                for r in reversed(rows[-25:])]

    def publish_today(self) -> None:
        self.publish(self.t("today"), json.dumps(self.today_summary()), True)
        try:
            self.publish_gallery()
        except Exception as err:   # the gallery is decoration: never break recognition over it
            LOG.warning("Species gallery failed: %s", err)

    # ---- species gallery ---------------------------------------------------------
    def gallery(self, now: float | None = None) -> list[dict[str, Any]]:
        """Species seen in the last GALLERY_DAYS days, newest first, with their latest visit."""
        now = now or time.time()
        today = datetime.fromtimestamp(now).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        items: dict[str, dict[str, Any]] = {}
        for r in self.db.q("""SELECT trace_id, ts, time, rec_species FROM visits WHERE rec_at IS NOT NULL AND ts >= ?
                              ORDER BY ts DESC""", now - GALLERY_DAYS * 86400):
            sp = r["rec_species"]
            if event_type(sp) != "bird" or sp == "Unknown bird":
                continue
            it = items.setdefault(sp, {"name": sp, "slug": slug(sp), "image": f"image.{self.s.ha_id}_{slug(sp)}_photo",
                                       "last_seen": r["time"] or datetime.fromtimestamp(r["ts"]).astimezone().isoformat(),
                                       "trace_id": r["trace_id"], "today": 0, "week": 0})
            it["week"] += 1
            it["today"] += int(r["ts"] >= today)
        colours = {x["species"]: x["dot"] for x in self.sightings(today)}
        for it in items.values():
            it["dot"] = colours.get(it["name"], "")
        return list(items.values())[:GALLERY_MAX]

    def portrait(self, trace_id: str) -> bytes | None:
        """The bird crop (if detected) or the whole frame of a visit's best frame, as a ~640 px JPEG."""
        from PIL import Image
        from .detect import square_crop_box
        f = self.db.one("""SELECT f.path, d.x1, d.y1, d.x2, d.y2 FROM frames f LEFT JOIN detections d ON d.frame_id=f.id
                           WHERE f.trace_id=? AND f.rejected=0
                           ORDER BY (d.frame_id IS NOT NULL) DESC, (f.kind='clip') DESC, f.score DESC LIMIT 1""",
                        trace_id)
        if not f:
            return None
        img = Image.open(self.s.image_dir / f["path"]).convert("RGB")
        if f["x1"] is not None:
            img = img.crop(square_crop_box([f["x1"], f["y1"], f["x2"], f["y2"]], *img.size, margin=0.6))
        img.thumbnail((640, 640))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        return buf.getvalue()

    def publish_gallery(self) -> None:
        items = self.gallery()
        for it in items:
            if self._gallery_sent.get(it["slug"]) == it["trace_id"]:
                continue
            if it["slug"] not in self._gallery_sent:
                topic, body = self.species_image_config(it["name"])
                self.publish(topic, json.dumps(body), True)
            photo = self.portrait(it["trace_id"])
            if photo:
                self.publish(self.t(f"species/{it['slug']}/image"), photo, True)
            self._gallery_sent[it["slug"]] = it["trace_id"]
        self.publish(self.t("gallery"), json.dumps({"count": len(items), "days": GALLERY_DAYS, "species": items}), True)

    # ---- loop ----------------------------------------------------------------------
    def start(self) -> None:
        threading.Thread(target=self._loop, name="recognition", daemon=True).start()

    def _loop(self) -> None:
        last_day = None
        while not self.stop.is_set():
            try:
                self.run_once()
                day = datetime.now().date()
                if day != last_day:        # midnight: reset "today" in HA
                    self.publish_today()
                    last_day = day
            except Exception as err:
                self.stats["last_error"] = str(err)[:200]
                LOG.exception("Recognition error")
            self.stop.wait(10)
