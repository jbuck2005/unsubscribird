"""The drafted GitHub Release takes its notes from RELEASES.md, unwrapped so GitHub shows one line per item."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("release_notes", ROOT / ".github/scripts/release_notes.py")
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

RELEASES = """# Release log

Intro text.

---

## 2.0.0 — 2030-01-02

A story that is wrapped
over two lines.

**New in this release**

- **First.** One item that is
  wrapped onto a second line.
- **Second.** Short.

```
code  stays
  as it is
```

---

## 1.0.0 — 2030-01-01

Older.
"""

CHANGELOG = """# Changelog

## 1.5.0

* A changelog item
  wrapped.

## 1.0.0

* Old.
"""


def write(tmp_path, releases=RELEASES, changelog=CHANGELOG):
    (tmp_path / "addon").mkdir()
    (tmp_path / "RELEASES.md").write_text(releases, encoding="utf-8")
    (tmp_path / "addon/CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_takes_the_releases_section_and_unwraps_it(tmp_path):
    out = rn.notes(write(tmp_path), "2.0.0", "Someone")
    assert out.startswith("A story that is wrapped over two lines.\n\n**New in this release**\n\n")
    assert "- **First.** One item that is wrapped onto a second line.\n- **Second.** Short.\n" in out
    assert "```\ncode  stays\n  as it is\n```" in out
    assert "Older." not in out and "Intro" not in out and "2030-01-02" not in out
    assert out.endswith("---\nImages: `ghcr.io/someone/unsubscribird:2.0.0` (amd64 and arm64).\n")


def test_a_version_prefix_does_not_match_a_longer_version(tmp_path):
    out = rn.notes(write(tmp_path, releases="## 1.0.10\n\nWrong.\n\n## 1.0.1\n\nRight.\n"), "1.0.1", "o")
    assert out.startswith("Right.\n")


def test_falls_back_to_the_changelog_then_to_a_pointer(tmp_path):
    write(tmp_path)
    assert rn.notes(tmp_path, "1.5.0", "o").startswith("* A changelog item wrapped.\n")
    assert rn.notes(tmp_path, "9.9.9", "o").startswith("See addon/CHANGELOG.md.\n")


def test_the_current_version_has_release_notes():
    """The current version must have a RELEASES.md section, so its draft isn't the changelog fallback."""
    import re
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "app/wbs/__init__.py").read_text()).group(1)
    assert rn.section((ROOT / "RELEASES.md").read_text(encoding="utf-8"), version)
