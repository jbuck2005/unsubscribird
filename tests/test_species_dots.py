"""The kids' page draws its own coloured dots in place of the species emoji, so every emoji needs one."""
from pathlib import Path

from wbs.recognition import DOTS

STATIC = Path(__file__).resolve().parents[1] / "app" / "wbs" / "static"


def test_every_species_emoji_has_a_css_dot():
    js, css = (STATIC / "kids.js").read_text(), (STATIC / "kids.css").read_text()
    for emoji in [*DOTS, "❔"]:
        assert f'"{emoji}": "' in js, emoji
        name = js.split(f'"{emoji}": "', 1)[1].split('"', 1)[0]
        assert f".dot-{name}" in css, name
