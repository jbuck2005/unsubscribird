"""One release a day: fails when another v* tag was already released on the same calendar day.

Run by release.yml before any image is built, so a second tag on the same day publishes nothing.

A release's day is the earliest of the dates we know for its tag:
  * the tagger date of an annotated tag, or the commit date of a lightweight one (git for-each-ref creatordate)
  * when its GitHub Release (draft or not) was created, passed in with --releases as JSON from the API
The day is counted in the time zone given with --tz (an IANA name such as "UTC" or "Europe/Paris").

Usage: python release_guard.py --tag v0.30.0 [--tz UTC] [--releases releases.json] [--today YYYY-MM-DD]
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def git_tag_dates():
    """(tag, aware datetime) for every v* tag in the checkout."""
    out = subprocess.run(
        ["git", "for-each-ref", "refs/tags/v*", "--format=%(refname:short) %(creatordate:iso-strict)"],
        check=True, capture_output=True, text=True).stdout
    for line in out.splitlines():
        tag, _, when = line.partition(" ")
        if when:
            yield tag, datetime.fromisoformat(when)


def release_dates(releases):
    """(tag, aware datetime) from a GitHub API list of releases."""
    for r in releases:
        if r.get("tag_name") and r.get("created_at"):
            yield r["tag_name"], datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))


def released_on(tag, today, entries, tz):
    """Other tags whose release day (in tz) is today. entries: iterable of (tag, aware datetime)."""
    first = {}
    for t, when in entries:
        if t == tag or not t.startswith("v"):
            continue
        day = when.astimezone(tz).date()
        first[t] = min(first.get(t, day), day)
    return sorted(t for t, day in first.items() if day == today)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--tag", required=True)
    p.add_argument("--tz", default="UTC")
    p.add_argument("--releases", help="JSON file: the repo's releases from the GitHub API")
    p.add_argument("--today", help="YYYY-MM-DD, for tests; default: today in --tz")
    a = p.parse_args(argv)
    tz = ZoneInfo(a.tz or "UTC")
    today = date.fromisoformat(a.today) if a.today else datetime.now(timezone.utc).astimezone(tz).date()
    entries = list(git_tag_dates())
    if a.releases:
        with open(a.releases) as f:
            entries += list(release_dates(json.load(f)))
    clash = released_on(a.tag, today, entries, tz)
    if clash:
        print(f"::error::{', '.join(clash)} {'was' if len(clash) == 1 else 'were'} already released on {today} ({a.tz}). One release a day: "
              f"nothing was published for {a.tag}. Re-run this workflow tomorrow, or delete the tag and push it again then.")
        return 1
    print(f"{a.tag}: the only release on {today} ({a.tz})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
