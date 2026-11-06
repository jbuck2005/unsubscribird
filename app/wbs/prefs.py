"""Long-term preferences, edited on the Settings page and saved in the database.

A saved value beats the stack's .env, which beats the default in config.py. Saved values live in /data, so they
survive redeploys and are in the nightly backup. Secrets and addresses the app needs to start stay in .env.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Pref:
    key: str                      # attribute on Settings
    group: str
    label: str
    help: str
    kind: str                     # float, int, bool, str, choice
    min: float | None = None
    max: float | None = None
    choices: tuple[tuple[str, str], ...] = ()
    unit: str = ""


PREFS = (
    Pref("site_name", "Kids' page", "Site name",
         "Shown on every page. Home Assistant's device name follows at the next app restart.", "str"),
    Pref("kids_sort", "Kids' page", "Clip order", "Used on devices where nobody has picked an order.", "choice",
         choices=(("new", "Newest first"), ("old", "Oldest first"), ("bird", "By bird"))),
    Pref("theme_default", "Kids' page", "Light or dark",
         "For all pages. Auto follows the sun. The ☀️/🌙 button still overrides it on a device.", "choice",
         choices=(("auto", "Auto (sunrise to sunset)"), ("light", "Always light"), ("dark", "Always dark"))),
    Pref("clip_skip_s", "Clips and frames", "Cut from the start of each clip",
         "Removes the camera's dark wake-up, at the first keyframe at or after this time (keyframes are 2 s apart). "
         "New clips only: clips already cut stay as they are. 0 = no cut.", "float", 0, 10, unit="s"),
    Pref("frames_per_visit", "Clips and frames", "Frames kept per visit", "New visits only.", "int", 1, 6),
    Pref("prelabel_paused", "Clips and frames", "Pause AI pre-labels",
         "Stops using LM Studio, to free the GPU. Clips, recognition and the kids' page keep working. New visits "
         "wait and catch up when you resume, within about 2 minutes.", "bool"),
    Pref("prelabel_frames", "Clips and frames", "Frames sent to LM Studio", "Per visit, best frames first.", "int", 1, 6),
    Pref("quiet_activity", "Clips and frames", "Quiet clip threshold",
         "Clips with less movement than this are suggested as Empty and skip LM Studio.", "float", 0, 1),
    Pref("ha_model_confidence", "Recognition", "Trust the model from",
         "Below this the local model's answer isn't reported as certain.", "float", 0, 1),
    Pref("ha_vlm_confidence", "Recognition", "Trust LM Studio from",
         "For species the model doesn't know yet.", "float", 0, 1),
    Pref("ha_wait_vlm_s", "Recognition", "Wait for LM Studio", "Then decide without it.", "int", 0, 86400, unit="s"),
    Pref("ha_max_age_h", "Recognition", "Ignore visits older than",
         "Older visits aren't sent to Home Assistant.", "float", 1, 168, unit="h"),
    Pref("auto_train", "Training", "Retrain every night", "Activates the new model only if it isn't worse.", "bool"),
    Pref("auto_train_hour", "Training", "Retrain at", "Hour of the day, 0-23.", "int", 0, 23, unit=":00"),
    Pref("auto_train_min_new", "Training", "New labels needed", "Skip the retrain with fewer than this.", "int", 1, 1000),
    Pref("region", "Location", "Region", "Told to LM Studio, to help it pick likely species.", "str"),
    Pref("sun_lat", "Location", "Latitude", "For sunrise and sunset.", "float", -90, 90),
    Pref("sun_lon", "Location", "Longitude", "West is negative.", "float", -180, 180),
)
BY_KEY = {p.key: p for p in PREFS}


def clean(p: Pref, value: Any) -> Any:
    """The value in its proper type, or ValueError with a message a person can act on."""
    if p.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"{p.label}: must be on or off")
    if p.kind == "choice":
        if value in [c[0] for c in p.choices]:
            return value
        raise ValueError(f"{p.label}: not one of the choices")
    if p.kind == "str":
        text = str(value).strip()
        if not text or len(text) > 200:
            raise ValueError(f"{p.label}: must be 1-200 characters")
        return text
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError
        if p.kind == "int":
            if number != int(number):
                raise ValueError
            number = int(number)
    except (TypeError, ValueError):
        raise ValueError(f"{p.label}: must be a {'whole ' if p.kind == 'int' else ''}number") from None
    if (p.min is not None and number < p.min) or (p.max is not None and number > p.max):
        raise ValueError(f"{p.label}: must be from {p.min:g} to {p.max:g}")
    return number


class Prefs:
    def __init__(self, settings, db) -> None:
        self.s, self.db = settings, db
        self.defaults = {p.key: getattr(settings, p.key) for p in PREFS}   # .env or config.py, before any saved value
        self.load()

    def saved(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self.db.q("SELECT key, value FROM prefs")}

    def load(self) -> None:
        saved = self.saved()
        for p in PREFS:
            value = self.defaults[p.key]
            if p.key in saved:
                try:
                    value = clean(p, saved[p.key])
                except ValueError:       # e.g. the allowed range changed: fall back rather than fail to start
                    pass
            setattr(self.s, p.key, value)

    def describe(self) -> list[dict[str, Any]]:
        saved = self.saved()
        return [{"key": p.key, "group": p.group, "label": p.label, "help": p.help, "kind": p.kind, "min": p.min,
                 "max": p.max, "unit": p.unit, "choices": [list(c) for c in p.choices],
                 "value": getattr(self.s, p.key), "default": self.defaults[p.key], "saved": p.key in saved}
                for p in PREFS]

    def save(self, changes: dict[str, Any]) -> None:
        """All or nothing. None or the default value clears the saved value, so a later default applies."""
        unknown = [k for k in changes if k not in BY_KEY]
        if unknown:
            raise ValueError(f"Not a setting: {unknown[0]}")
        cleaned = {k: None if v is None else clean(BY_KEY[k], v) for k, v in changes.items()}
        with self.db.tx() as c:
            for key, value in cleaned.items():
                if value is None or value == self.defaults[key]:
                    c.execute("DELETE FROM prefs WHERE key=?", (key,))
                else:
                    c.execute("""INSERT INTO prefs(key, value, updated) VALUES (?,?,?)
                                 ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated""",
                              (key, json.dumps(value), time.time()))
        self.load()
