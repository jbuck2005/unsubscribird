"""Starts the web app. As a Home Assistant add-on, first turns the add-on's options (and the MQTT broker the
Supervisor knows about) into WBS_* settings. Anywhere else, .env already set them and this changes nothing."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

OPTIONS = Path("/data/options.json")
IMAGES = "/media/unsubscribird"     # clips and frames: in HA's media folder, out of the add-on's own backup
# CPU priority as an add-on (0 normal, 19 lowest). Home Assistant shares the computer and comes first: embedding,
# training and ffmpeg (which inherits it) only get the CPU it leaves free.
NICE = 15
LOG = logging.getLogger("wbs.start")

# add-on option -> setting. Empty options are left out, so the defaults in config.py apply.
OPTION_ENV = {
    "site_name": "WBS_SITE_NAME",
    "admin_password": "WBS_ADMIN_PASSWORD",
    "host": "WBS_HOST",
    "public_url": "WBS_PUBLIC_URL",
    "allowed_hosts": "WBS_ALLOWED_HOSTS",
    "lmstudio_url": "WBS_LMSTUDIO_URL",
    "lmstudio_model": "WBS_LMSTUDIO_MODEL",
    "bridge_topic": "WBS_BRIDGE_TOPIC",
    "ha_id": "WBS_HA_ID",
    "embed_threads": "WBS_EMBED_THREADS",
    "detect": "WBS_DETECT",
    "mqtt_host": "WBS_MQTT_HOST",
    "mqtt_port": "WBS_MQTT_PORT",
    "mqtt_user": "WBS_MQTT_USER",
    "mqtt_password": "WBS_MQTT_PASSWORD",
}


def environment(options: dict, mqtt: dict) -> dict[str, str]:
    """The settings for an add-on with these options. mqtt is the Supervisor's broker; options override it."""
    env = {"WBS_INGRESS": "true", "WBS_DATA_DIR": "/data", "WBS_IMAGE_DIR": IMAGES,
           "WBS_HA_HOST": "homeassistant", "WBS_HA_URL": "http://homeassistant:8123"}
    if mqtt:
        env |= {"WBS_MQTT_HOST": str(mqtt.get("host", "")), "WBS_MQTT_PORT": str(mqtt.get("port", 1883)),
                "WBS_MQTT_USER": str(mqtt.get("username", "")), "WBS_MQTT_PASSWORD": str(mqtt.get("password", ""))}
    for option, name in OPTION_ENV.items():
        value = options.get(option)
        if isinstance(value, bool):
            env[name] = "true" if value else "false"
        elif value not in (None, ""):
            env[name] = str(value)
    return env


def mqtt_service(token: str) -> dict:
    """The MQTT broker the Supervisor offers (the Mosquitto add-on), or {} without one."""
    try:
        r = requests.get("http://supervisor/services/mqtt", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return (r.json().get("data") or {}) if r.ok else {}
    except (requests.RequestException, ValueError):
        return {}


def main() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token and OPTIONS.exists():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        mqtt = mqtt_service(token)
        LOG.info("Home Assistant add-on; MQTT broker %s", "from the Supervisor" if mqtt else "from the options")
        os.environ.update(environment(json.loads(OPTIONS.read_text()), mqtt))
        Path(IMAGES).mkdir(parents=True, exist_ok=True)
        os.nice(NICE)
    os.execvp("uvicorn", ["uvicorn", "wbs.main:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers"])


if __name__ == "__main__":
    main()
