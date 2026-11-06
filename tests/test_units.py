import numpy as np

from wbs import frames
from wbs.prelabel import consensus, parse_json


def test_parse_json_handles_think_and_fences():
    txt = '<think>hmm {not json}</think>\n```json\n{"bird_present": true, "species": "Blue Jay", "confidence": 0.9}\n```'
    assert parse_json(txt) == {"bird_present": True, "species": "Blue Jay", "confidence": 0.9}
    assert parse_json("no json here") is None


def test_consensus_bird_beats_empty_frames():
    s = [{"bird_present": False}, {"bird_present": True, "species": "Blue Jay", "confidence": 0.9},
         {"bird_present": True, "species": "Blue Jay", "confidence": 0.8}]
    c = consensus(s)
    assert c["species"] == "Blue Jay" and c["votes"] == 2 and c["frames"] == 3 and c["confidence"] == 0.85


def test_consensus_empty_and_squirrel():
    assert consensus([{"bird_present": False}, {"bird_present": False}])["species"] == "Empty"
    assert consensus([{"bird_present": False, "other_animal": "Eastern gray squirrel"}])["species"] == "Squirrel"
    assert consensus([{"bird_present": True, "species": None}])["species"] == "Unknown bird"
    assert consensus([]) is None


def make_clip(n=20, bird_at=(8, 12)):
    rng = np.random.default_rng(0)
    base = rng.integers(60, 120, (frames.AH, frames.AW)).astype(np.uint8)
    out = np.repeat(base[None], n, axis=0).copy()
    for i in range(*bird_at):  # a bright "bird" blob moving across
        x = 100 + (i - bird_at[0]) * 10
        out[i, 80:130, x:x + 40] = 230
    return out


def test_scores_prefer_frames_with_the_bird():
    scores = frames.score_frames(make_clip())
    best = int(np.argmax(scores))
    assert 8 <= best < 12
    picks = frames.choose(scores, k=3, min_gap_s=1.0)
    assert len(picks) == 3 and all(abs(a.t - b.t) >= 1.0 for a, b in zip(picks, picks[1:]))
    assert any(8 / frames.FPS <= p.t < 12 / frames.FPS for p in picks)


def test_overlay_strip_is_ignored():
    clip = make_clip(bird_at=(0, 0))
    clip[5, :10, :] = 255  # timestamp ticking in the top strip
    assert max(frames.score_frames(clip)) <= 0.01


def test_still_clip_falls_back_to_sharpness():
    clip = make_clip(bird_at=(0, 0))
    scores = frames.score_frames(clip)
    assert len(scores) == 20 and max(scores) <= 0.01


def test_no_padding_with_empty_frames_when_a_bird_was_seen():
    scores = [0.0] * 20
    scores[3], scores[9] = 0.9, 0.5
    picks = frames.choose(scores, k=4)
    assert [p.t for p in picks] == [1.5, 4.5]
    assert len(frames.choose([0.004] * 20, k=4)) == 4  # nothing moved: still return k frames


def test_backfill_parses_trace_time():
    from wbs.backfill import parse
    r = parse("0000000017938810222aBcDeFgHiJ.mp4\n")
    assert r["trace_id"] == "0000000017938810222aBcDeFgHiJ" and r["timestamp"] == 1793881022.0
    assert r["clip_url"] == "/local/vicohome/0000000017938810222aBcDeFgHiJ.mp4"
    assert parse(".part.mp4") is None and parse("notes.txt") is None


def test_consensus_tie_prefers_the_bird():
    s = [{"bird_present": False, "other_animal": "squirrel", "confidence": 0.95},
         {"bird_present": True, "species": "Blue Jay", "confidence": 0.95}]
    assert consensus(s)["species"] == "Blue Jay"


def test_camera_wakeup_frame_does_not_crowd_out_the_bird():
    clip = make_clip(bird_at=(8, 12))
    clip[0] = np.clip(clip[0].astype(int) + 90, 0, 255).astype(np.uint8)   # exposure jump on the first frame
    clip[1] = 255 - clip[1]                                                 # whole-picture change (camera shake)
    scores = frames.score_frames(clip)
    assert 8 <= int(np.argmax(scores)) < 12
    picks = frames.choose(scores, k=4)
    assert sum(8 / frames.FPS <= p.t < 12 / frames.FPS for p in picks) >= 2   # bird frames survive the 15% cut


def test_repick_label_fit_rule():
    from wbs.repick import fits
    assert fits("Blue Jay", {"bird_present": True}) and not fits("Blue Jay", {"bird_present": False})
    assert fits("Empty", {"bird_present": False}) and not fits("Empty", {"bird_present": False, "other_animal": "squirrel"})
    assert fits("Squirrel", {"other_animal": "squirrel"}) and fits("Blue Jay", None) is None
