"""Settings from environment variables (see .env.example). prefs.py overlays what is saved on the Settings page."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


OLD_PREFIX = "WBS_"         # before 0.29.0; still read, so an existing .env keeps working
OLD_NAMES_USED: set[str] = set()


def _env(name: str, default: str = "") -> str:
    """UNSUB_X, or else the old WBS_X (noted in OLD_NAMES_USED for a startup warning), or else `default`.
    An empty UNSUB_X still lets an old WBS_X through: the compose file passes empty values for anything left out."""
    if os.environ.get(name, "").strip():
        return os.environ[name].strip()
    old = OLD_PREFIX + name.removeprefix("UNSUB_")
    if os.environ.get(old, "").strip():
        OLD_NAMES_USED.add(old)
        return os.environ[old].strip()
    return os.environ.get(name, default).strip()


env = _env


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("UNSUB_DATA_DIR", "/data")))
    image_dir: Path = field(default_factory=lambda: Path(_env("UNSUB_IMAGE_DIR", "/images")))
    # The three computers (see .env.example). The URLs below come from these unless set outright.
    host: str = field(default_factory=lambda: _env("UNSUB_HOST", "localhost"))         # runs this app
    ha_host: str = field(default_factory=lambda: _env("UNSUB_HA_HOST", "localhost"))   # Home Assistant
    ai_host: str = field(default_factory=lambda: _env("UNSUB_AI_HOST"))                # LM Studio; empty = no pre-labels
    mqtt_host: str = field(default_factory=lambda: _env("UNSUB_MQTT_HOST") or _env("UNSUB_HA_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(_env("UNSUB_MQTT_PORT", "1883")))
    mqtt_user: str = field(default_factory=lambda: _env("UNSUB_MQTT_USER"))
    mqtt_password: str = field(default_factory=lambda: _env("UNSUB_MQTT_PASSWORD"))
    bridge_topic: str = field(default_factory=lambda: _env("UNSUB_BRIDGE_TOPIC", "vicohome_mqtt"))
    ha_url: str = field(default_factory=lambda: (
        _env("UNSUB_HA_URL") or f"http://{_env('UNSUB_HA_HOST', 'localhost')}:8123").rstrip("/"))
    lmstudio_url: str = field(default_factory=lambda: (
        _env("UNSUB_LMSTUDIO_URL") or (f"http://{_env('UNSUB_AI_HOST')}:1234" if _env("UNSUB_AI_HOST") else "")).rstrip("/"))
    lmstudio_model: str = field(default_factory=lambda: _env("UNSUB_LMSTUDIO_MODEL", ""))
    # Only use a model LM Studio already has loaded (never make it load/swap models on the PC).
    lmstudio_require_loaded: bool = field(
        default_factory=lambda: _env("UNSUB_LMSTUDIO_REQUIRE_LOADED", "true").lower() in ("1", "true", "yes"))
    # Keep LM Studio's GPU free for something else. New visits wait and catch up on resume.
    prelabel_paused: bool = field(default_factory=lambda: _env("UNSUB_PRELABEL_PAUSED", "false").lower() in ("1", "true", "yes"))
    frames_per_visit: int = field(default_factory=lambda: int(_env("UNSUB_FRAMES_PER_VISIT", "4")))
    prelabel_frames: int = field(default_factory=lambda: int(_env("UNSUB_PRELABEL_FRAMES", "3")))
    embed_enabled: bool = field(default_factory=lambda: _env("UNSUB_EMBED", "true").lower() in ("1", "true", "yes"))
    embed_threads: int = field(default_factory=lambda: int(_env("UNSUB_EMBED_THREADS", "4")))
    ha_publish: bool = field(default_factory=lambda: _env("UNSUB_HA_PUBLISH", "true").lower() in ("1", "true", "yes"))
    ha_topic: str = field(default_factory=lambda: _env("UNSUB_HA_TOPIC", "unsubscribird"))
    # Home Assistant's id for this device. Changing it makes new entities, so it isn't on the Settings page.
    ha_id: str = field(default_factory=lambda: _env("UNSUB_HA_ID", "unsubscribird"))
    site_name: str = field(default_factory=lambda: _env("UNSUB_SITE_NAME", "un-subscribird"))
    ha_discovery_prefix: str = field(default_factory=lambda: _env("UNSUB_HA_DISCOVERY_PREFIX", "homeassistant"))
    ha_model_confidence: float = field(default_factory=lambda: float(_env("UNSUB_HA_MODEL_CONFIDENCE", "0.75")))
    ha_vlm_confidence: float = field(default_factory=lambda: float(_env("UNSUB_HA_VLM_CONFIDENCE", "0.8")))
    ha_wait_vlm_s: int = field(default_factory=lambda: int(_env("UNSUB_HA_WAIT_VLM_S", "600")))
    ha_model_instant: float = field(default_factory=lambda: float(_env("UNSUB_HA_MODEL_INSTANT", "0.98")))
    ha_max_age_h: float = field(default_factory=lambda: float(_env("UNSUB_HA_MAX_AGE_H", "6")))
    public_url: str = field(default_factory=lambda: (
        _env("UNSUB_PUBLIC_URL") or f"http://{_env('UNSUB_HOST', 'localhost')}:{_env('UNSUB_PORT', '8095')}").rstrip("/"))
    # More host names the web app answers to (comma list), besides UNSUB_HOST, public_url's and localhost.
    # Others get a 400.
    extra_hosts: str = field(default_factory=lambda: _env("UNSUB_ALLOWED_HOSTS"))
    # Running as a Home Assistant add-on (set by start.py): the HA sidebar (Ingress) opens every page, with HA's
    # own login, for requests from the Supervisor only.
    ingress: bool = field(default_factory=lambda: _env("UNSUB_INGRESS", "false").lower() in ("1", "true", "yes"))
    # Clips whose best activity score is below this had nothing move in them: no LM Studio, suggested Empty.
    # Measured 2026-11-05 on 55 clips: birds >= 0.061, 18 of 24 empty visits < 0.03.
    quiet_activity: float = field(default_factory=lambda: float(_env("UNSUB_QUIET_ACTIVITY", "0.025")))
    # Home Assistant's REST API, only to read the temperature sensor below. Docker: a long-lived token
    # (HA profile page, Security); the add-on uses its own Supervisor token.
    ha_api_url: str = field(default_factory=lambda: (_env("UNSUB_HA_API_URL") or (
        _env("UNSUB_HA_URL") or f"http://{_env('UNSUB_HA_HOST', 'localhost')}:8123") + "/api").rstrip("/"))
    ha_token: str = field(default_factory=lambda: _env("UNSUB_HA_TOKEN"))
    temp_sensor: str = field(default_factory=lambda: _env("UNSUB_TEMP_SENSOR"))
    # Hours without a bird, at a time of day that is usually busy, before Home Assistant hears "feeder quiet".
    feeder_quiet_h: float = field(default_factory=lambda: float(_env("UNSUB_FEEDER_QUIET_H", "3")))
    auto_train: bool = field(default_factory=lambda: _env("UNSUB_AUTO_TRAIN", "true").lower() in ("1", "true", "yes"))
    auto_train_hour: int = field(default_factory=lambda: int(_env("UNSUB_AUTO_TRAIN_HOUR", "2")))
    auto_train_days: int = field(default_factory=lambda: int(_env("UNSUB_AUTO_TRAIN_DAYS", "1")))
    auto_train_min_new: int = field(default_factory=lambda: int(_env("UNSUB_AUTO_TRAIN_MIN_NEW", "5")))
    detect_enabled: bool = field(default_factory=lambda: _env("UNSUB_DETECT", "true").lower() in ("1", "true", "yes"))
    region: str = field(default_factory=lambda: _env("UNSUB_REGION", "Ottawa, Ontario, Canada"))
    # The camera wakes up dark (or washed out) for ~1.5 s: clips shown to people skip this many seconds.
    # The original clip.mp4 is kept untouched for the frame picker and training. 0 turns trimming off.
    kids_sort: str = field(default_factory=lambda: _env("UNSUB_KIDS_SORT", "new"))
    theme_default: str = field(default_factory=lambda: _env("UNSUB_THEME", "auto"))
    # Where the feeder is: light theme from sunrise to sunset there (default Ottawa).
    sun_lat: float = field(default_factory=lambda: float(_env("UNSUB_LAT", "45.42")))
    sun_lon: float = field(default_factory=lambda: float(_env("UNSUB_LON", "-75.70")))
    # The camera wakes up dark (or washed out) for ~1.5 s (measured 2026-11-05: settled by 1.5 s). Each clip is
    # cut once, in place, right after download and before frames are picked (visits.clip_cut records it), at the
    # first keyframe at or after this many seconds (no re-encode; the camera's keyframes are 2 s apart).
    # 0 turns cutting off for new clips.
    clip_skip_s: float = field(default_factory=lambda: float(_env("UNSUB_CLIP_SKIP_SECONDS", "2")))
    # Delete the clip (only the clip) of a visit a person confirmed as Empty, this many days after the visit. 0 = keep.
    empty_clip_days: int = field(default_factory=lambda: int(_env("UNSUB_EMPTY_CLIP_DAYS", "14")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wbs.sqlite3"

    @property
    def allowed_hosts(self) -> list[str]:
        extra = [h.strip() for h in self.extra_hosts.split(",") if h.strip()]
        names = [self.host, urlsplit(self.public_url).hostname or "localhost", "localhost", "127.0.0.1", *extra]
        return list(dict.fromkeys(names))


settings = Settings()
