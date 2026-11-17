"""Notes for a drafted GitHub Release: this version's section of RELEASES.md, made readable on GitHub.

Run by release.yml's draft job. The section is the text under "## <version>" (the heading may carry a date, as in
"## 0.30.0 — 2026-11-17") up to the next "## " heading or "---" rule. If RELEASES.md has no section for the version,
the section of addon/CHANGELOG.md is used instead, and failing that a pointer to the changelog.

The files are wrapped at 120 characters. GitHub shows every line break in a release as a break, so wrapped lines are
joined back into one line per paragraph or list item. Fenced code blocks are left exactly as they are.

Usage: python release_notes.py --version 0.30.0 [--root .] [--owner jbuck2005]
"""
import argparse
import re
import sys
from pathlib import Path

LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")


def section(text, version):
    """The lines under "## <version>" up to the next "## " heading or "---" rule, or None if there is no such heading."""
    head = re.compile(rf"^## {re.escape(version)}(\s|$)")
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if head.match(line):
            body = []
            for line in lines[i + 1:]:
                if line.startswith("## ") or line.strip() == "---":
                    break
                body.append(line)
            return body
    return None


def unwrap(lines):
    """Joins wrapped lines into one line per paragraph or list item. Blank lines, headings and fences stay put."""
    out, fenced = [], False
    for line in lines:
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append(line)
            continue
        starts_block = (fenced or not line.strip() or line.lstrip().startswith("#") or LIST_ITEM.match(line)
                        or not out or not out[-1].strip() or out[-1].lstrip().startswith(("#", "```")))
        if starts_block:
            out.append(line.rstrip())
        else:
            out[-1] = f"{out[-1].rstrip()} {line.strip()}"
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def notes(root, version, owner):
    root = Path(root)
    body = None
    for name in ("RELEASES.md", "addon/CHANGELOG.md"):
        path = root / name
        if path.exists():
            body = section(path.read_text(encoding="utf-8"), version)
            if body and any(line.strip() for line in body):
                break
            body = None
    text = "\n".join(unwrap(body)) if body else "See addon/CHANGELOG.md."
    image = f"ghcr.io/{owner.lower()}/unsubscribird:{version}"
    return f"{text}\n\n---\nImages: `{image}` (amd64 and arm64).\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--version", required=True)
    p.add_argument("--root", default=".")
    p.add_argument("--owner", default="jbuck2005")
    a = p.parse_args(argv)
    sys.stdout.write(notes(a.root, a.version, a.owner))


if __name__ == "__main__":
    main()
