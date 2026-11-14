"""The release workflow: one release a day, and the GitHub Release is only ever drafted."""
import importlib.util
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("release_guard", ROOT / ".github/scripts/release_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

UTC = ZoneInfo("UTC")


def at(day, hour, tz=timezone.utc):
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(tzinfo=tz)


def test_a_second_tag_on_the_same_day_is_refused():
    entries = [("v1.0.0", at("2030-01-02", 9)), ("v1.0.1", at("2030-01-02", 15))]
    assert guard.released_on("v1.0.1", date(2030, 1, 2), entries, UTC) == ["v1.0.0"]


def test_the_next_day_is_fine_and_the_tag_itself_does_not_count():
    entries = [("v1.0.0", at("2030-01-02", 9)), ("v1.0.1", at("2030-01-03", 9))]
    assert guard.released_on("v1.0.1", date(2030, 1, 3), entries, UTC) == []


def test_the_day_follows_the_time_zone():
    # 02:00 UTC on the 3rd is still the evening of the 2nd five hours west.
    west = timezone(timedelta(hours=-5))
    entries = [("v1.0.0", at("2030-01-03", 2))]
    assert guard.released_on("v1.0.1", date(2030, 1, 3), entries, UTC) == ["v1.0.0"]
    assert guard.released_on("v1.0.1", date(2030, 1, 3), entries, west) == []


def test_a_release_counts_from_its_earliest_date():
    # An old tag whose GitHub Release was drafted again today is not today's release.
    entries = [("v1.0.0", at("2030-01-01", 9)), ("v1.0.0", at("2030-01-05", 9))]
    assert guard.released_on("v1.1.0", date(2030, 1, 5), entries, UTC) == []


def test_release_dates_read_the_api_shape():
    got = list(guard.release_dates([{"tag_name": "v1.0.0", "created_at": "2030-01-02T09:00:00Z"}, {"tag_name": "x"}]))
    assert got == [("v1.0.0", at("2030-01-02", 9))]


def test_the_script_against_a_real_checkout(tmp_path):
    def git(*a, date=None):
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date} if date else {}
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                       check=True, capture_output=True, env={**__import__("os").environ, **env})
    git("init", "-q")
    git("commit", "-q", "--allow-empty", "-m", "one", date="2030-01-02T09:00:00Z")
    git("tag", "v1.0.0")
    releases = tmp_path / "releases.json"
    releases.write_text(json.dumps([]))
    run = lambda today: subprocess.run(
        ["python3", str(ROOT / ".github/scripts/release_guard.py"), "--tag", "v1.0.1", "--tz", "UTC",
         "--releases", str(releases), "--today", today], cwd=tmp_path, capture_output=True, text=True)
    refused = run("2030-01-02")
    assert refused.returncode == 1 and "v1.0.0 was already released" in refused.stdout
    assert run("2030-01-03").returncode == 0


def test_the_workflow_only_drafts_the_release():
    wf = (ROOT / ".github/workflows/release.yml").read_text()
    assert "release_guard.py" in wf
    assert "gh release create" in wf and "--draft" in wf
    assert "--draft=false" not in wf and "gh release edit" not in wf
