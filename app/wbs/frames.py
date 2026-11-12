"""Pick the most useful frames from a visit clip and save them at full resolution.

The clip is decoded small (320 px, grey, 2 fps) for scoring. Each frame is scored on
  * change: how much it differs from the clip's median frame (a bird that came and went),
  * motion: difference from the previous frame (a bird moving),
  * sharpness: variance of a Laplacian (blurred frames make poor training data).
The best frames, at least `min_gap` seconds apart, are then cut from the clip at full size.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

LOG = logging.getLogger("unsub.frames")

AW, AH, FPS = 320, 180, 2.0      # analysis size and rate
OVERLAY_ROWS = 0.12              # the camera's date/time stamp lives in the top strip: ignore it
CHANGE_THRESHOLD = 25            # grey levels
GLOBAL_CHANGE = 0.5              # share of the picture: above this it is a camera/lighting event


@dataclass
class Pick:
    t: float
    score: float


OLD_VIEW_NAME = "clip_view.mp4"   # 0.14.1-0.15.0 kept a second, trimmed copy; now removed
MIN_KEEP_S = 2.0   # never cut a clip below this


def keyframes(path: Path) -> list[float]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
                          "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    times = []
    for line in out.split():          # some ffprobe builds print "2.007000," (trailing separator)
        x = line.split(",")[0].strip()
        if x and x != "N/A":
            times.append(float(x))
    return times


def trim_start(clip: Path, skip: float) -> float:
    """Cut the camera's dark wake-up off the start of clip.mp4, in place. Returns the seconds cut (0 = unchanged).

    No re-encode: a stream copy starting at the first keyframe at or after `skip` (the camera puts keyframes
    every 2.007 s, so the default 2 s cuts at 2.007 s). Lossless and the file gets smaller. At least
    MIN_KEEP_S stays; no keyframe within 0.5 s after `skip` = clip left as is. Checked (length = original - cut) before it
    replaces the original; faststart so it plays at once on hover.
    """
    if skip <= 0:
        return 0.0
    dur = probe(clip)[0]
    kf = next((k for k in keyframes(clip) if k >= skip - 0.05), None)
    # A late keyframe (a few clips have none until ~4 s) would cut more than asked: leave those clips whole.
    if kf is None or kf <= 0 or kf > skip + 0.5 or dur - kf < MIN_KEEP_S:
        return 0.0
    tmp = clip.with_name("clip.trim.part.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{kf + 0.001:.3f}", "-i", str(clip),
                    "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(tmp)],
                   capture_output=True, timeout=120, check=True)
    got = probe(tmp)[0]
    if abs(got - (dur - kf)) > 0.3:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"trimmed clip is {got:.2f} s, expected {dur - kf:.2f} s")
    tmp.replace(clip)
    return kf

def probe(path: Path) -> tuple[float, int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    info = json.loads(out)
    st = info["streams"][0]
    return float(info["format"]["duration"]), int(st["width"]), int(st["height"])


def decode_small(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vf",
                          f"fps={FPS},scale={AW}:{AH},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=300, check=True).stdout
    n = len(raw) // (AW * AH)
    return np.frombuffer(raw[: n * AW * AH], dtype=np.uint8).reshape(n, AH, AW)


def sharpness(img: np.ndarray) -> float:
    f = img.astype(np.float32)
    lap = (-4 * f[1:-1, 1:-1] + f[:-2, 1:-1] + f[2:, 1:-1] + f[1:-1, :-2] + f[1:-1, 2:])
    return float(lap.var())


def score_frames(frames: np.ndarray) -> list[float]:
    if len(frames) == 0:
        return []
    body = frames[:, int(AH * OVERLAY_ROWS):, :].astype(np.int16)
    # Remove each frame's overall brightness so exposure changes (the camera waking up, sun/cloud) don't count.
    body = body - np.median(body, axis=(1, 2), keepdims=True).astype(np.int16)
    median = np.median(body, axis=0)
    change = (np.abs(body - median) > CHANGE_THRESHOLD).mean(axis=(1, 2))
    # Motion counts only if a frame differs from BOTH neighbours (a moving bird). Plain frame-to-frame
    # difference would also reward the empty frame right after the bird left.
    motion = np.zeros(len(body))
    if len(body) > 2:
        step = (np.abs(np.diff(body, axis=0)) > CHANGE_THRESHOLD).mean(axis=(1, 2))  # step[i] = |f[i+1]-f[i]|
        motion[1:-1] = np.minimum(step[:-1], step[1:])
    sharp = np.array([sharpness(f) for f in frames[:, int(AH * OVERLAY_ROWS):, :]])
    sharp_n = sharp / sharp.max() if sharp.max() > 0 else np.ones_like(sharp)
    activity = np.maximum(change, motion)
    # A change over most of the picture is the camera (exposure step, shake, refocus), not a bird: damp it so
    # it can't crowd out the frames where a bird actually is.
    activity = np.where(activity > GLOBAL_CHANGE, activity * 0.05, activity)
    if activity.max() < 0.003:   # nothing moved: just prefer sharp frames
        return list(sharp_n * 0.01)
    return list(activity * np.sqrt(sharp_n))


def motion_box(frames: np.ndarray, index: int, min_pixels: int = 30) -> list[float] | None:
    """Largest changed region of one analysed frame vs the clip's median, as [x1, y1, x2, y2] in 0..1.

    Finds birds that come and go (or move); a bird sitting still for the whole clip is part of the median
    and is not found here - the image detector covers that case."""
    from scipy import ndimage
    top = int(AH * OVERLAY_ROWS)
    body = frames[:, top:, :].astype(np.int16)
    body = body - np.median(body, axis=(1, 2), keepdims=True).astype(np.int16)
    mask = np.abs(body[index] - np.median(body, axis=0)) > CHANGE_THRESHOLD
    if mask.mean() > GLOBAL_CHANGE:          # whole-picture change: not a bird
        return None
    mask = ndimage.binary_opening(mask, iterations=1)
    lab, n = ndimage.label(mask)
    if not n:
        return None
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    if sizes[k - 1] < min_pixels:
        return None
    ys, xs = np.where(lab == k)
    return [round(xs.min() / AW, 4), round((ys.min() + top) / AH, 4),
            round((xs.max() + 1) / AW, 4), round((ys.max() + 1 + top) / AH, 4)]


def choose(scores: list[float], k: int, min_gap_s: float = 1.5) -> list[Pick]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    picks: list[Pick] = []
    best = scores[order[0]] if order else 0.0
    for i in order:
        # When something clearly moved, don't pad with near-empty frames.
        if picks and best > 0.05 and scores[i] < 0.15 * best:
            break
        t = i / FPS
        if all(abs(t - p.t) >= min_gap_s for p in picks):
            picks.append(Pick(t, float(scores[i])))
        if len(picks) == k:
            break
    return sorted(picks, key=lambda p: p.t)


def cut(path: Path, t: float, out: Path, width: int | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = ["-vf", f"scale={width}:-2"] if width else []
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(path),
                    "-frames:v", "1", *vf, "-q:v", "2", "-y", str(out)],
                   capture_output=True, timeout=120, check=True)


def extract_best(clip: Path, out_dir: Path, k: int, info: dict | None = None) -> list[dict]:
    """Returns [{t, score, path, thumb, width, height}] for the k best frames.
    If `info` is given, info['activity'] is set to the clip's highest activity score."""
    duration, w, h = probe(clip)
    small = decode_small(clip)
    scores = score_frames(small)
    if info is not None:
        info["activity"] = float(max(scores)) if scores else 0.0
    picks = choose(scores, k)
    results = []
    for p in picks:
        t = min(p.t, max(0.0, duration - 0.2))
        name = f"f{int(round(t * 10)):04d}"
        full, thumb = out_dir / f"{name}.jpg", out_dir / f"{name}_thumb.jpg"
        cut(clip, t, full)
        cut(clip, t, thumb, width=480)
        idx = min(int(round(p.t * FPS)), len(small) - 1)
        results.append({"t": round(t, 2), "score": round(p.score, 5), "path": full, "thumb": thumb,
                        "width": w, "height": h, "motion_box": motion_box(small, idx)})
    LOG.debug("%s: picked %s", clip.name, [r["t"] for r in results])
    return results


def replacement_time(clip: Path, exclude: list[float], min_gap_s: float = 1.0) -> float | None:
    """Pick another moment from the clip after a person rejected a frame (usually for blur).

    Among the frames where something is happening (>= 15% of the best activity score, or all frames if
    nothing moved), take the SHARPEST one that is at least `min_gap_s` from every frame already used or
    rejected. If none is left, fall back to the sharpest frame anywhere in the clip.
    """
    small = decode_small(clip)
    if len(small) == 0:
        return None
    scores = score_frames(small)
    sharp = [sharpness(f[int(AH * OVERLAY_ROWS):, :]) for f in small]
    best = max(scores)
    active = [i for i in range(len(scores)) if best <= 0.05 or scores[i] >= 0.15 * best]

    def free(i: int) -> bool:
        return all(abs(i / FPS - e) >= min_gap_s for e in exclude)

    for pool in (active, range(len(scores))):
        for i in sorted(pool, key=lambda i: (sharp[i], scores[i]), reverse=True):
            if free(i):
                return round(i / FPS, 2)
    return None
