"""eBird checklists (Cornell Lab), as a file to upload yourself: "eBird Record Format (Extended)".

One checklist per day: every bird species the camera saw that day, with the most seen at once in one visit. Upload
it at eBird's "Import data" page in your own account; nothing is sent from here.

The format, from eBird's "Upload spreadsheet data" help (2025): .csv, no header row, 19 columns in a fixed order, no
quotation marks or line breaks, dates MM/DD/YYYY, times HH:MM, duration in minutes, "All observations reported?"
Y or N, a count or X ("present, not counted"), one date and one location per checklist, at most 1 MB per file.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from . import feederwatch
from .db import DB

PROTOCOLS = {"stationary": "Stationary", "incidental": "Incidental"}


def clean(value: Any) -> str:
    """eBird refuses quotation marks and line breaks, and the file has no quoting: commas go too."""
    return " ".join(str(value).replace('"', "").replace(",", " ").split())


def checklists(db: DB, settings, first: date, last: date) -> list[dict[str, Any]]:
    """One checklist per day from `first` to `last` with at least one bird."""
    days = (last - first).days + 1
    fw = feederwatch.count(db, first, days)
    sci = {r["name"]: (r["scientific"] or "").split() for r in db.q("SELECT name, scientific FROM species")}
    out = []
    for e in fw["effort"]:
        d = e["day"]
        rows = [s for s in fw["species"] if d in s["days"]]
        if not rows:
            continue
        first_t, last_t = (datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M") for t in (e["first"], e["last"]))
        out.append({"day": d, "start": e["first"], "minutes": max(1, int((last_t - first_t).total_seconds() // 60) + 1),
                    "visits": e["bird_visits"],
                    "species": [{"species": s["species"], "scientific": " ".join(sci.get(s["species"], [])[:2]),
                                 "number": s["counted"].get(d) or "X", "visits": s["day_visits"].get(d, 0)}
                                for s in sorted(rows, key=lambda s: s["species"])]})
    return out


def to_csv(lists: list[dict[str, Any]], settings) -> str:
    protocol = PROTOCOLS.get(settings.ebird_protocol, "Stationary")
    stationary = protocol == "Stationary"
    lines = []
    for c in lists:
        y, m, dd = c["day"].split("-")
        note = (f"Feeder camera; species and counts from un-subscribird. {c['visits']} bird visits from {c['start']}. "
                "Counts are the most seen at once in one clip.")
        for s in c["species"]:
            genus, _, epithet = s["scientific"].partition(" ")
            lines.append(",".join(clean(v) for v in (
                s["species"], genus, epithet, s["number"], f"{s['visits']} visit{'' if s['visits'] == 1 else 's'}",
                settings.ebird_location, settings.sun_lat, settings.sun_lon, f"{m}/{dd}/{y}", c["start"],
                settings.ebird_state, settings.ebird_country, protocol, 1,
                c["minutes"] if stationary else "", "Y" if stationary else "N", "", "", note)))
    return "\n".join(lines) + ("\n" if lines else "")
