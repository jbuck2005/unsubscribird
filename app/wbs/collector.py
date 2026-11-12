"""Collect visits from the Vicohome MQTT bridge: snapshot, MP4 clip and the best frames.

Topics (from ha-vicohome-bridge):
  <base>/<serial>/last   newest visit record (JSON, retained)
  <base>/<serial>/today  today's summary incl. the 10 most recent visits with clip_url (JSON, retained)
  <base>/<serial>/image  newest snapshot (JPEG bytes, retained) - published just before `last`
Clips are fetched from Home Assistant's /local/... URL (the bridge keeps only the newest N there).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
import requests

from . import frames as framelib
from .config import Settings
from .db import DB

LOG = logging.getLogger("unsub.collector")
# When to try each clip download, in seconds after the visit arrived. The gaps grow so a Home Assistant restart
# or reboot (the clip is served by Home Assistant) is waited out: the last try is 15 minutes in.
CLIP_RETRY_AT_S = (0, 10, 20, 40, 80, 160, 300, 480, 660, 900)
MAX_CLIP_ATTEMPTS = len(CLIP_RETRY_AT_S)
RECHECK_EVERY_S = 300        # check recent clips again this often...
RECHECK_WINDOW_S = 45 * 60   # ...for visits up to this old (the bridge re-saves for 30 minutes)...
RECHECK_MIN_AGE_S = 120      # ...once the first download had time to happen
NO_CLIP_GRACE_S = 30 * 60
# A bird that sits still barely changes the clip, so a quiet clip's best frame goes to OWL-ViT first. On real
# feeder clips it found the bird in every quiet clip that had one (0.36-0.76) and nothing in the empty ones.
STILL_BIRD_SCORE = 0.3
MAX_CLIP_BYTES = 200 * 1024 * 1024
# MQTT is input, not truth: a trace id becomes a folder name and a clip_url is appended to Home Assistant's address.
TRACE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
CLIP_URL = re.compile(r"/local(/[A-Za-z0-9_-]+)+\.mp4")


def valid_trace(trace_id: Any) -> bool:
    return isinstance(trace_id, str) and TRACE_ID.fullmatch(trace_id) is not None


def visit_dir(settings: Settings, trace_id: str, ts: float) -> Path:
    if not valid_trace(trace_id):
        raise ValueError(f"bad trace id {trace_id!r}")
    d = datetime.fromtimestamp(ts)
    return settings.image_dir / "visits" / d.strftime("%Y/%m/%d") / trace_id


def rel(settings: Settings, path: Path) -> str:
    return str(path.relative_to(settings.image_dir))


def save_capped(src, path: Path) -> None:
    """Write a download to path, giving up past MAX_CLIP_BYTES."""
    size = 0
    with open(path, "wb") as fh:
        while chunk := src.read(1 << 20):
            size += len(chunk)
            if size > MAX_CLIP_BYTES:
                raise RuntimeError(f"clip is over {MAX_CLIP_BYTES} bytes")
            fh.write(chunk)


def clip_due(v, now: float) -> bool:
    """True when the next clip download try for visit row v is due (see CLIP_RETRY_AT_S)."""
    attempts = v["attempts"]
    return attempts < MAX_CLIP_ATTEMPTS and now >= v["created"] + CLIP_RETRY_AT_S[attempts]


def record_from_recent(serial: str, r: dict[str, Any]) -> dict[str, Any] | None:
    if not valid_trace(r.get("trace_id")) or not r.get("time"):
        return None
    return {"trace_id": r["trace_id"], "serial": serial, "timestamp": datetime.fromisoformat(r["time"]).timestamp(),
            "time": r["time"], "bird": r.get("bird"), "confidence": r.get("confidence"),
            "clip_url": r.get("clip_url")}


class Collector:
    def __init__(self, settings: Settings, db: DB) -> None:
        self.s, self.db = settings, db
        self.latest_image: dict[str, tuple[bytes, float]] = {}
        self.latest_trace: dict[str, str] = {}
        self.stats = {"mqtt": "starting", "messages": 0, "clips": 0, "last_error": ""}
        self.stop = threading.Event()
        self.http = requests.Session()
        self.client = None
        self.on_connected = None        # callable() run after every (re)connect, e.g. HA discovery
        self.detector = None            # OWL-ViT (detect.Detector), when enabled: overrules "nothing moved"

    def still_animal(self, trace: str) -> dict[str, Any] | None:
        """OWL-ViT's bird or squirrel in the visit's best clip frame, if it is sure enough; None otherwise."""
        if self.detector is None:
            return None
        f = self.db.one("""SELECT path FROM frames WHERE trace_id=? AND kind='clip' AND rejected=0
                           ORDER BY score DESC LIMIT 1""", trace)
        if not f:
            return None
        try:
            from PIL import Image
            with Image.open(self.s.image_dir / f["path"]) as img:
                det = self.detector.owl(img.convert("RGB"))
        except Exception as err:   # no verdict: fall back to the motion score alone
            LOG.warning("Visit %s: OWL-ViT check failed: %s", trace, err)
            return None
        return det if det and det["score"] >= STILL_BIRD_SCORE else None

    # ---- MQTT -----------------------------------------------------------
    def start(self) -> None:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="unsubscribird")
        if self.s.mqtt_user:
            c.username_pw_set(self.s.mqtt_user, self.s.mqtt_password)
        c.on_connect = self._on_connect
        c.on_disconnect = lambda *a: self.stats.update(mqtt="disconnected")
        c.on_message = self._on_message
        c.reconnect_delay_set(1, 60)
        if self.s.ha_publish:
            c.will_set(f"{self.s.ha_topic}/status", "offline", qos=1, retain=True)
        self.client = c                 # before connecting: on_connect publishes through it
        c.connect_async(self.s.mqtt_host, self.s.mqtt_port, keepalive=60)
        c.loop_start()
        threading.Thread(target=self._worker, name="collector", daemon=True).start()

    def _on_connect(self, client, userdata, flags, reason, properties=None) -> None:
        if reason.is_failure:
            self.stats["mqtt"] = f"refused: {reason}"
            LOG.error("MQTT connect refused: %s", reason)
            return
        self.stats["mqtt"] = "connected"
        b = self.s.bridge_topic
        for sub in ("last", "today", "image"):
            client.subscribe(f"{b}/+/{sub}")
        client.subscribe(f"{self.s.ha_discovery_prefix}/status")
        LOG.info("MQTT connected, listening on %s/+/{last,today,image}", b)
        if self.on_connected:
            threading.Thread(target=self.on_connected, daemon=True).start()

    def _on_message(self, client, userdata, msg) -> None:
        self.stats["messages"] += 1
        try:
            if msg.topic == f"{self.s.ha_discovery_prefix}/status":
                if msg.payload == b"online" and self.on_connected:
                    LOG.info("Home Assistant came online: re-sending discovery")
                    threading.Thread(target=self.on_connected, daemon=True).start()
                return
            parts = msg.topic.split("/")
            serial, kind = parts[-2], parts[-1]
            if kind == "image":
                self.on_image(serial, msg.payload)
            elif kind == "last":
                self.on_last(serial, json.loads(msg.payload))
            elif kind == "today":
                self.on_today(serial, json.loads(msg.payload))
        except Exception:  # never let one bad message kill the MQTT thread
            LOG.exception("Bad message on %s", msg.topic)

    def publish(self, topic: str, payload, retain: bool) -> None:
        if self.client is not None:
            self.client.publish(topic, payload, qos=1, retain=retain)

    # ---- handlers (also called directly by tests) -------------------------
    def on_image(self, serial: str, data: bytes) -> None:
        self.latest_image[serial] = (data, time.time())
        trace = self.latest_trace.get(serial)
        if trace:
            self._attach_snapshot(serial, trace)

    def on_last(self, serial: str, rec: dict[str, Any]) -> None:
        if not rec.get("trace_id"):
            return
        if not valid_trace(rec["trace_id"]):
            LOG.warning("Ignoring a visit with a bad trace id: %r", rec["trace_id"])
            return
        rec = {**rec, "serial": serial}
        if self.db.upsert_visit(rec):
            LOG.info("New visit %s at %s (Vicohome: %s)", rec["trace_id"], rec.get("time"), rec.get("bird"))
        self.latest_trace[serial] = rec["trace_id"]
        self._attach_snapshot(serial, rec["trace_id"])

    def on_today(self, serial: str, today: dict[str, Any]) -> None:
        for r in today.get("recent") or []:
            rec = record_from_recent(serial, r)
            if rec and self.db.upsert_visit(rec):
                LOG.info("Visit %s picked up from the recent list", rec["trace_id"])

    def _attach_snapshot(self, serial: str, trace_id: str) -> None:
        img = self.latest_image.get(serial)
        row = self.db.one("SELECT ts, snapshot FROM visits WHERE trace_id=?", trace_id)
        if not img or not row or row["snapshot"]:
            return
        data, received = img
        if time.time() - received > 300:
            return
        path = visit_dir(self.s, trace_id, row["ts"]) / "snapshot.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.db.set_visit(trace_id, snapshot=rel(self.s, path))
        self.db.add_frame(trace_id, "snapshot", rel(self.s, path), rel(self.s, path), None, None, None, None)

    # ---- clip + frames worker -----------------------------------------------
    def _worker(self) -> None:
        last_recheck = 0.0
        while not self.stop.is_set():
            try:
                self.process_pending()
                if time.time() - last_recheck >= RECHECK_EVERY_S:
                    last_recheck = time.time()
                    self.refetch_recent(RECHECK_WINDOW_S / 3600, min_age_s=RECHECK_MIN_AGE_S)
            except Exception as err:
                self.stats["last_error"] = str(err)[:200]
                LOG.exception("Collector worker error")
            self.stop.wait(10)

    # ---- clips that grew after download ------------------------------------------------
    # The camera bridge may save a clip before the cloud has the whole video and replace it later, under the same
    # name (ha-vicohome-bridge 0.3.5 re-checks for 30 minutes). So recent clips are checked again, and on demand
    # ("Fetch clips again" on the Status page) any from the last hours.
    def refresh_clip(self, v) -> str:
        """Download the visit's clip again if Home Assistant now has a bigger one. Returns what happened:
        "grew", "same", "gone" (HA no longer has it) or "error: ..."."""
        trace = v["trace_id"]
        try:
            if not v["clip"] or not v["clip_url"] or not CLIP_URL.fullmatch(v["clip_url"]):
                return "same"
            clip = self.s.image_dir / v["clip"]
            r = self.http.get(f"{self.s.ha_url}{v['clip_url']}", timeout=60, stream=True, allow_redirects=False)
            if r.status_code != 200:
                r.close()
                return "gone"
            have = v["clip_bytes"] or (clip.stat().st_size if clip.exists() else 0)
            offered = int(r.headers.get("Content-Length") or 0)
            # Clearly bigger only: an older download's size isn't recorded, and the cut file is a bit smaller.
            if offered and offered <= have * (1.0 if v["clip_bytes"] else 1.25):
                r.close()
                return "same"
            tmp = clip.with_suffix(".part")
            try:
                save_capped(r.raw, tmp)
                new_len = framelib.probe(tmp)[0]
                old_len = framelib.probe(clip)[0] + (v["clip_cut"] or 0) if clip.exists() else 0
                if new_len < old_len + 1:
                    return "same"
                size = tmp.stat().st_size
                tmp.replace(clip)
            finally:
                tmp.unlink(missing_ok=True)
            cut = framelib.trim_start(clip, self.s.clip_skip_s)
            self.db.set_visit(trace, clip_bytes=size, clip_cut=cut)
            if not self.db.one("SELECT 1 FROM labels WHERE trace_id=?", trace):
                self.repick_frames(trace, clip)   # a labelled visit keeps the frames a person chose
            LOG.info("Visit %s: clip grew to %.1f s, fetched again", trace, new_len)
            return "grew"
        except Exception as err:
            LOG.warning("Visit %s: fetching the clip again failed: %s", trace, err)
            return f"error: {str(err)[:120]}"

    def repick_frames(self, trace: str, clip) -> None:
        """New frames from the longer clip; the old clip frames are marked rejected (kept on disk, never used)."""
        info: dict = {}
        new_ids = [self.db.add_frame(trace, "clip", rel(self.s, f["path"]), rel(self.s, f["thumb"]), f["t"], f["score"],
                                     f["width"], f["height"], f.get("motion_box"))
                   for f in framelib.extract_best(clip, clip.parent, self.s.frames_per_visit, info)]
        with self.db.tx() as c:
            c.execute(f"UPDATE frames SET rejected=0 WHERE id IN ({','.join('?' * len(new_ids))})", new_ids)
            c.execute(f"""UPDATE frames SET rejected=1 WHERE trace_id=? AND kind='clip'
                          AND id NOT IN ({','.join('?' * len(new_ids))})""", (trace, *new_ids))
        self.db.set_visit(trace, activity=info.get("activity"))

    def refetch_recent(self, hours: float, min_age_s: float = 0) -> dict:
        """Check every visit with a clip from the last `hours` hours; returns counts per outcome."""
        now = time.time()
        rows = self.db.q("""SELECT * FROM visits WHERE clip IS NOT NULL AND clip_url IS NOT NULL AND ts >= ? AND ts <= ?
                            ORDER BY ts""", now - hours * 3600, now - min_age_s)
        counts: dict = {"checked": len(rows), "grew": 0, "same": 0, "gone": 0, "errors": 0}
        for v in rows:
            out = self.refresh_clip(v)
            counts["errors" if out.startswith("error") else out] += 1
        return counts

    def process_pending(self) -> None:
        now = time.time()
        rows = self.db.q("""SELECT * FROM visits WHERE status='new' AND attempts < ? AND ts < ?
                            ORDER BY ts DESC LIMIT 200""", MAX_CLIP_ATTEMPTS, now - 20)
        for v in rows:
            if v["clip_url"]:
                if clip_due(v, now):
                    self.fetch_clip(v)
            elif now - v["ts"] > NO_CLIP_GRACE_S:
                # No clip ever appeared: keep the visit with just its snapshot.
                self.db.set_visit(v["trace_id"], status="frames" if v["snapshot"] else "failed",
                                  error=None if v["snapshot"] else "no clip and no snapshot")

    def fetch_clip(self, v) -> None:
        trace = v["trace_id"]
        try:
            out_dir = visit_dir(self.s, trace, v["ts"])
            clip = out_dir / "clip.mp4"
            if not clip.exists():
                if not CLIP_URL.fullmatch(v["clip_url"]):
                    raise RuntimeError(f"bad clip_url {v['clip_url']!r}")
                r = self.http.get(f"{self.s.ha_url}{v['clip_url']}", timeout=60, stream=True, allow_redirects=False)
                if r.status_code != 200:
                    raise RuntimeError(f"clip HTTP {r.status_code}")
                out_dir.mkdir(parents=True, exist_ok=True)
                tmp = clip.with_suffix(".part")
                try:
                    save_capped(r.raw, tmp)
                    framelib.probe(tmp)   # only a real video becomes clip.mp4
                    size = tmp.stat().st_size
                    tmp.rename(clip)
                    self.db.set_visit(trace, clip_bytes=size)
                finally:
                    tmp.unlink(missing_ok=True)
            row = self.db.one("SELECT clip_cut FROM visits WHERE trace_id=?", trace)
            if row is None or row["clip_cut"] is None:   # cut the dark camera wake-up once, before picking frames
                try:
                    cut = framelib.trim_start(clip, self.s.clip_skip_s)
                except Exception as err:   # keep the uncut clip rather than lose the visit
                    LOG.warning("Visit %s: clip cut failed, kept uncut: %s", trace, err)
                    cut = 0.0
                self.db.set_visit(trace, clip_cut=cut)
            info: dict = {}
            for f in framelib.extract_best(clip, out_dir, self.s.frames_per_visit, info):
                self.db.add_frame(trace, "clip", rel(self.s, f["path"]), rel(self.s, f["thumb"]), f["t"],
                                  f["score"], f["width"], f["height"], f.get("motion_box"))
            activity = info.get("activity", 1.0)
            if activity < self.s.quiet_activity and (seen := self.still_animal(trace)):
                LOG.info("Visit %s: little movement (activity %.3f) but OWL-ViT sees a %s (%.2f)",
                         trace, activity, seen["label"], seen["score"])
                self.db.set_visit(trace, clip=rel(self.s, clip), status="frames", error=None, activity=activity)
            elif activity < self.s.quiet_activity:
                # Nothing moved: skip LM Studio (and features until confirmed); suggest Empty for one-key review.
                self.db.add_suggestion(trace, None, "motion", "frame-picker", {
                    "bird_present": False, "species": "Empty", "confidence": 0.9,
                    "notes": f"nothing moved in the clip (activity {activity:.3f} < {self.s.quiet_activity})"}, "")
                self.db.set_visit(trace, clip=rel(self.s, clip), status="prelabelled", error=None,
                                  activity=activity, quiet=1)
            else:
                self.db.set_visit(trace, clip=rel(self.s, clip), status="frames", error=None, activity=activity)
            self.stats["clips"] += 1
            LOG.info("Visit %s: clip saved, frames extracted", trace)
        except Exception as err:
            attempts = v["attempts"] + 1
            self.db.set_visit(trace, attempts=attempts, error=str(err)[:300],
                              status="failed" if attempts >= MAX_CLIP_ATTEMPTS and not v["snapshot"] else "new")
            if attempts >= MAX_CLIP_ATTEMPTS and v["snapshot"]:
                self.db.set_visit(trace, status="frames")
            LOG.warning("Visit %s: clip failed (%d/%d): %s", trace, attempts, MAX_CLIP_ATTEMPTS, err)
