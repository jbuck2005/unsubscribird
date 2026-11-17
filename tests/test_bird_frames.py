"""Review: only frames where the detector boxed a bird start ticked for training."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "wbs"
JS = (APP / "static" / "app.js").read_text()


def _pick(name: str) -> str:
    """The source of one top-level const or one Review method from app.js."""
    if name == "defaultFrames":
        m = re.search(r"\n  defaultFrames\(v, species\) \{.*?\n  \},\n", JS, re.S)
        return "function defaultFrames(v, species) {" + m.group(0).split("{", 1)[1].rsplit(",", 1)[0]
    m = re.search(rf"\nconst {name} = .*?;\n", JS, re.S)
    return m.group(0)


def run_default(visit: dict, species: str) -> list[int]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    src = _pick("NOT_BIRDS") + _pick("birdBoxed") + _pick("defaultFrames") + \
        f"\nconsole.log(JSON.stringify(defaultFrames({json.dumps(visit)}, {json.dumps(species)})));"
    out = subprocess.run([node, "-e", src], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def frame(i, source=None, label=None):
    return {"id": i, "kind": "clip", "det_source": source, "det_label": label}


def visit(frames, suggestions=()):
    return {"frames": frames, "suggestions": list(suggestions)}


def test_only_bird_boxed_frames_start_ticked():
    v = visit([frame(1, "owlvit", "bird"), frame(2, "motion"), frame(3), frame(4, "owlvit", "bird"),
               frame(5, "owlvit", "squirrel")],
              # LM Studio thinks every frame has a bird: the detector's box still decides.
              [{"frame_id": i, "bird_present": 1, "other_animal": None} for i in range(1, 6)])
    assert run_default(v, "Black-capped Chickadee") == [1, 4]


def test_no_bird_box_falls_back_to_lm_studio():
    v = visit([frame(1, "motion"), frame(2), frame(3)],
              [{"frame_id": 1, "bird_present": 1, "other_animal": None},
               {"frame_id": 2, "bird_present": 0, "other_animal": None}])
    assert run_default(v, "Black-capped Chickadee") == [1, 3]   # frame 3 has no LM Studio answer: kept


def test_animals_and_empty_ignore_the_bird_box():
    v = visit([frame(1, "owlvit", "bird"), frame(2, "owlvit", "squirrel")],
              [{"frame_id": 1, "bird_present": 0, "other_animal": "squirrel"},
               {"frame_id": 2, "bird_present": 0, "other_animal": None}])
    assert run_default(v, "Squirrel") == [1]
    assert run_default(v, "Empty") == [2]


def test_review_help_mentions_the_yellow_box():
    html = (APP / "templates" / "review.html").read_text()
    assert "yellow box" in html and "yellow box" in JS
