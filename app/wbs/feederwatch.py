"""Project FeederWatch counts (Cornell Lab / Birds Canada, November to April).

A FeederWatch count covers two consecutive days. For each species you report the most birds seen AT ONCE, not
the number of visits (the same chickadee comes back all day). The camera sees one visit at a time, so the most
birds in any one visit is the count. A count you typed on the Review page wins; otherwise LM Studio's largest
count for that species in the visit's frames; otherwise 1.

Nothing is sent anywhere: you copy the numbers into FeederWatch yourself.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta
from typing import Any

from .db import DB

NOT_COUNTED = ("Empty", "Uncertain", "Unknown bird", "Other animal")


def day_bounds(d: date) -> tuple[float, float]:
    start = datetime(d.year, d.month, d.day).astimezone()
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def visit_count(db: DB, trace_id: str, species: str, typed: int | None) -> tuple[int, str]:
    """How many of `species` this visit showed at once, and where the number came from."""
    if typed:
        return int(typed), "you"
    rows = db.q("""SELECT MAX(count) n FROM suggestions WHERE trace_id=? AND source='vlm' AND bird_present=1
                   AND LOWER(species)=LOWER(?) AND count > 0""", trace_id, species)
    if rows and rows[0]["n"]:
        return int(rows[0]["n"]), "LM Studio"
    return 1, "one bird"


def count(db: DB, first_day: date, days: int = 2) -> dict[str, Any]:
    """Per bird species over `days` days from `first_day`: the most seen at once, per day and overall."""
    birds = {r["name"] for r in db.q("SELECT name FROM species WHERE kind='bird'")} - set(NOT_COUNTED)
    day_list = [first_day + timedelta(days=i) for i in range(days)]
    species: dict[str, dict[str, Any]] = {}
    effort = []
    for d in day_list:
        start, end = day_bounds(d)
        rows = db.q("""SELECT v.trace_id, v.ts, COALESCE(l.species, v.rec_species) shown, l.count, l.also
                       FROM visits v LEFT JOIN labels l USING(trace_id)
                       WHERE v.ts >= ? AND v.ts < ? AND v.excluded=0
                         AND (l.species IS NOT NULL OR v.rec_at IS NOT NULL) ORDER BY v.ts""", start, end)
        seen: dict[str, float] = {}     # bird visits, each once even with two species in it
        for r in rows:
            also = [s for s in json.loads(r["also"] or "[]") if s != r["shown"]]
            for sp, typed in [(r["shown"], r["count"]), *[(s, None) for s in also]]:
                if sp not in birds:
                    continue
                seen[r["trace_id"]] = r["ts"]
                n, source = visit_count(db, r["trace_id"], sp, typed)
                it = species.setdefault(sp, {"species": sp, "max": 0, "visits": 0, "days": {}, "trace_id": None,
                                             "source": "", "day_visits": {}, "counted": {}})
                it["visits"] += 1
                it["days"][d.isoformat()] = max(it["days"].get(d.isoformat(), 0), n)
                it["day_visits"][d.isoformat()] = it["day_visits"].get(d.isoformat(), 0) + 1
                if source != "one bird":   # a real count (yours or LM Studio's), not the "at least one" fallback
                    it["counted"][d.isoformat()] = max(it["counted"].get(d.isoformat(), 0), n)
                if n > it["max"]:
                    it.update(max=n, trace_id=r["trace_id"], source=source)
        local = [datetime.fromtimestamp(t) for t in seen.values()]
        effort.append({"day": d.isoformat(), "bird_visits": len(local),
                       "am": sum(t.hour < 12 for t in local), "pm": sum(t.hour >= 12 for t in local),
                       "first": local[0].strftime("%H:%M") if local else None,
                       "last": local[-1].strftime("%H:%M") if local else None})
    return {"days": [d.isoformat() for d in day_list], "effort": effort,
            "species": sorted(species.values(), key=lambda s: (-s["max"], s["species"]))}


def to_csv(result: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Species", "Most at once", *[f"Most at once {d}" for d in result["days"]], "Visits", "Count from"])
    for s in result["species"]:
        w.writerow([s["species"], s["max"], *[s["days"].get(d, 0) for d in result["days"]], s["visits"], s["source"]])
    return buf.getvalue()
