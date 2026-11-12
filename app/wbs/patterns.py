"""When birds come: visits by hour of day, by week through the season, and by outdoor temperature. Plus the
quiet-feeder check: no visits for hours at a time of day that is usually busy suggests an empty feeder.

The temperature comes from a Home Assistant sensor you name (Settings, "Temperature sensor"), sampled every
10 minutes into the weather table. It needs a Home Assistant token: UNSUB_HA_TOKEN with Docker; the add-on uses
its own. Nothing else is fetched from anywhere.
"""

from __future__ import annotations

import bisect
import json
import logging
import threading
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import requests

from .db import DB

LOG = logging.getLogger("wbs.patterns")
NOT_SHOWN = ("Empty", "Uncertain", "Unknown bird", "Other animal")
SAMPLE_S = 600
KEEP_WEATHER_DAYS = 400
BAND = 5                  # degrees per temperature band
QUIET_LOOKBACK_DAYS = 14  # "usually busy" means: on average over the last two weeks
QUIET_MIN_EXPECTED = 5    # visits normally seen in the quiet hours before it counts as unusual


def sightings(db: DB, start: float, end: float | None = None) -> list[tuple[float, str]]:
    """(time, species) for every animal seen from `start`: each visit's species and its Also seen ones."""
    rows = db.q("""SELECT v.ts, COALESCE(l.species, v.rec_species) shown, l.also FROM visits v
                   LEFT JOIN labels l USING(trace_id)
                   WHERE v.ts >= ? AND v.ts < ? AND v.excluded=0 AND (l.species IS NOT NULL OR v.rec_at IS NOT NULL)
                   ORDER BY v.ts""", start, end or time.time() + 1)
    out = []
    for r in rows:
        for sp in [r["shown"], *[s for s in json.loads(r["also"] or "[]") if s != r["shown"]]]:
            if sp and sp not in NOT_SHOWN:
                out.append((r["ts"], sp))
    return out


def by_hour(db: DB, days: int, now: float | None = None) -> dict[str, Any]:
    """Visits per species and hour of day (local time) over the last `days` days, busiest species first."""
    now = now or time.time()
    seen = sightings(db, now - days * 86400, now)
    table: dict[str, list[int]] = {}
    for ts, sp in seen:
        table.setdefault(sp, [0] * 24)[datetime.fromtimestamp(ts).hour] += 1
    return {"days": days, "species": sorted(table, key=lambda s: -sum(table[s])), "counts": table}


def by_week(db: DB, weeks: int = 26, now: float | None = None) -> dict[str, Any]:
    """Visits per species and week (weeks start on Monday), the last `weeks` weeks, oldest first."""
    now = now or time.time()
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    first = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    seen = sightings(db, first.timestamp(), now)
    table: dict[str, list[int]] = {}
    for ts, sp in seen:
        table.setdefault(sp, [0] * weeks)[min((datetime.fromtimestamp(ts) - first).days // 7, weeks - 1)] += 1
    return {"weeks": [(first + timedelta(weeks=i)).date().isoformat() for i in range(weeks)],
            "species": sorted(table, key=lambda s: -sum(table[s])), "counts": table}


def by_temperature(db: DB, days: int, now: float | None = None) -> dict[str, Any] | None:
    """Bird visits per hour spent in each temperature band, counting only the hours of the day the feeder is
    busy (so cold nights don't make cold look quiet). None without temperature samples."""
    now = now or time.time()
    start = now - days * 86400
    samples = db.q("SELECT ts, temp, unit FROM weather WHERE ts >= ? AND ts < ? ORDER BY ts", start, now)
    if not samples:
        return None
    seen = sightings(db, start, now)
    hours = Counter(datetime.fromtimestamp(ts).hour for ts, _ in seen)
    busy = {h for h, n in hours.items() if n >= max(1, 0.01 * len(seen))}
    bands: dict[int, dict[str, float]] = {}
    for s in samples:
        if datetime.fromtimestamp(s["ts"]).hour in busy:
            b = bands.setdefault(int(s["temp"] // BAND) * BAND, {"hours": 0.0, "visits": 0})
            b["hours"] += SAMPLE_S / 3600
    stamps = [s["ts"] for s in samples]
    for ts, _ in seen:
        i = _nearest(stamps, ts)
        if abs(stamps[i] - ts) <= SAMPLE_S and datetime.fromtimestamp(ts).hour in busy:
            b = bands.setdefault(int(samples[i]["temp"] // BAND) * BAND, {"hours": 0.0, "visits": 0})
            b["visits"] += 1
    return {"unit": samples[-1]["unit"] or "°", "band": BAND, "busy_hours": sorted(busy),
            "samples": len(samples), "latest": {"temp": samples[-1]["temp"], "ts": samples[-1]["ts"]},
            "bands": [{"from": k, "to": k + BAND, "hours": round(v["hours"], 1), "visits": int(v["visits"]),
                       "per_hour": round(v["visits"] / v["hours"], 2) if v["hours"] >= 1 else None}
                      for k, v in sorted(bands.items())]}


def current(db: DB, now: float | None = None) -> dict[str, Any] | None:
    """The latest outdoor temperature, if it is fresh (within three samples), for the home page."""
    r = db.one("SELECT ts, temp, unit FROM weather ORDER BY ts DESC LIMIT 1")
    if not r or (now or time.time()) - r["ts"] > 3 * SAMPLE_S:
        return None
    return {"temp": round(r["temp"]), "unit": r["unit"] or "°", "ts": r["ts"]}


def _nearest(stamps: list[float], ts: float) -> int:
    i = bisect.bisect_left(stamps, ts)
    if i == 0:
        return 0
    if i == len(stamps):
        return len(stamps) - 1
    return i if stamps[i] - ts < ts - stamps[i - 1] else i - 1


def feeder_quiet(db: DB, quiet_h: float, now: float | None = None) -> dict[str, Any]:
    """Is the feeder unusually quiet? No bird visits in the last `quiet_h` hours, when the same hours of the day
    have brought at least QUIET_MIN_EXPECTED visits on average over the last two weeks."""
    now = now or time.time()
    if quiet_h <= 0:
        return {"quiet": False, "enabled": False}
    start = now - quiet_h * 3600
    recent = [ts for ts, _ in sightings(db, start, now)]
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    past = sightings(db, (today - timedelta(days=QUIET_LOOKBACK_DAYS)).timestamp(), today.timestamp())
    # Visits on the earlier days in the same clock window (e.g. 10:00 to 13:00), averaged per day. By the
    # clock, not seconds ago, so a change to or from daylight saving time doesn't move the window.
    def clock(ts: float) -> float:
        t = datetime.fromtimestamp(ts)
        return t.hour * 3600 + t.minute * 60 + t.second
    end_s = clock(now)
    def in_window(ts: float) -> bool:
        return 0 <= (end_s - clock(ts)) % 86400 <= quiet_h * 3600
    expected = sum(in_window(ts) for ts, _ in past) / QUIET_LOOKBACK_DAYS
    last = db.one("""SELECT MAX(v.ts) t FROM visits v LEFT JOIN labels l USING(trace_id)
                     WHERE v.excluded=0 AND COALESCE(l.species, v.rec_species) NOT IN ('Empty', 'Uncertain')""")["t"]
    return {"enabled": True, "quiet": not recent and expected >= QUIET_MIN_EXPECTED, "hours": quiet_h,
            "expected": round(expected, 1), "recent": len(recent), "last_visit": last}


class WeatherSampler:
    """Every 10 minutes: the temperature sensor's state from Home Assistant, into the weather table."""

    def __init__(self, settings, db: DB, api_url: str, token: str) -> None:
        self.s, self.db, self.api_url, self.token = settings, db, api_url.rstrip("/"), token
        self.stop = threading.Event()
        self.http = requests.Session()
        self.last_error = ""

    def read(self) -> tuple[float, str] | None:
        entity = (self.s.temp_sensor or "").strip()
        if not entity or not self.token:
            return None
        r = self.http.get(f"{self.api_url}/states/{entity}", headers={"Authorization": f"Bearer {self.token}"},
                          timeout=10, allow_redirects=False)
        r.raise_for_status()
        st = r.json()
        attrs = st.get("attributes") or {}
        if entity.startswith("weather."):
            return float(attrs["temperature"]), attrs.get("temperature_unit", "")
        return float(st["state"]), attrs.get("unit_of_measurement", "")

    def sample(self) -> None:
        try:
            got = self.read()
            self.last_error = ""
        except (requests.RequestException, KeyError, TypeError, ValueError) as err:
            self.last_error = str(err)[:200]
            LOG.warning("Temperature sensor: %s", self.last_error)
            return
        if got is None:
            return
        with self.db.tx() as c:
            c.execute("INSERT OR REPLACE INTO weather(ts, temp, unit) VALUES (?,?,?)", (time.time(), *got))
            c.execute("DELETE FROM weather WHERE ts < ?", (time.time() - KEEP_WEATHER_DAYS * 86400,))

    def start(self) -> None:
        threading.Thread(target=self._loop, name="weather", daemon=True).start()

    def _loop(self) -> None:
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(SAMPLE_S)
