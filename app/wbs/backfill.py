"""Seed visits from clip file names that are already on Home Assistant.

Usage (on the computer running the app):
  ssh root@homeassistant.local 'ls /config/www/vicohome' | docker exec -i unsubscribird python -m wbs.backfill
Vicohome trace ids embed the visit's unix time in characters 8-17.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

from .config import settings
from .db import DB

TRACE = re.compile(r"^(?P<trace>[0-9]{8}(?P<ts>[0-9]{10})[A-Za-z0-9_-]+)\.mp4$")


def parse(name: str) -> dict | None:
    m = TRACE.match(name.strip())
    if not m:
        return None
    ts = int(m["ts"])
    if not 1_600_000_000 < ts < 2_500_000_000:
        return None
    return {"trace_id": m["trace"], "timestamp": float(ts), "time": datetime.fromtimestamp(ts).astimezone().isoformat(),
            "clip_url": f"/local/vicohome/{m['trace']}.mp4"}


def main() -> None:
    db = DB(settings.db_path)
    new = 0
    for line in sys.stdin:
        rec = parse(line)
        if rec and db.upsert_visit(rec):
            new += 1
    print(f"{new} new visit(s) queued")


if __name__ == "__main__":
    main()
