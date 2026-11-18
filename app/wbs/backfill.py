"""Seed visits from clip file names that are already on Home Assistant.

Usage (on the computer running the app):
  ssh root@homeassistant.local 'ls /config/www/vicohome' | docker exec -i unsubscribird python -m wbs.backfill [folder]
`folder` is the bridge's clip_folder (default vicohome), the folder under /config/www that holds the clips.
Vicohome trace ids embed the visit's unix time in characters 8-17.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime

from .config import settings
from .db import DB

TRACE = re.compile(r"^(?P<trace>[0-9]{8}(?P<ts>[0-9]{10})[A-Za-z0-9_-]+)\.mp4$")


FOLDER = re.compile(r"[A-Za-z0-9_-]+")


def parse(name: str, folder: str = "vicohome") -> dict | None:
    m = TRACE.match(name.strip())
    if not m:
        return None
    ts = int(m["ts"])
    if not 1_600_000_000 < ts < 2_500_000_000:
        return None
    return {"trace_id": m["trace"], "timestamp": float(ts), "time": datetime.fromtimestamp(ts).astimezone().isoformat(),
            "clip_url": f"/local/{folder}/{m['trace']}.mp4"}


def main() -> None:
    folder = sys.argv[1].strip("/") if len(sys.argv) > 1 else "vicohome"
    if not FOLDER.fullmatch(folder):
        sys.exit("folder: letters, digits, _ and - only (the bridge's clip_folder)")
    db = DB(settings.db_path)
    new = 0
    for line in sys.stdin:
        rec = parse(line, folder)
        if rec and db.upsert_visit(rec):
            new += 1
    print(f"{new} new visit(s) queued")


if __name__ == "__main__":
    main()
