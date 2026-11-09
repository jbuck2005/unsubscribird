"""Starts the web app. As a Home Assistant add-on, first turns the add-on's options (and the MQTT broker the
Supervisor knows about) into WBS_* settings. Anywhere else, .env already set them and this changes nothing."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests

OPTIONS = Path("/data/options.json")
IMAGES = "/media/unsubscribird"     # clips and frames: in HA's media folder, out of the add-on's own backup
# CPU priority as an add-on (0 normal, 19 lowest). Home Assistant shares the computer and comes first: embedding,
# training and ffmpeg (which inherits it) only get the CPU it leaves free.
NICE = 15
MEMINFO = Path("/proc/meminfo")
MIN_MEMORY_GIB = 7
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


def low_memory(meminfo: str) -> str | None:
    """A warning when the computer has less memory than the models need alongside Home Assistant, else None.
    8 GB computers report about 7.6 GiB; a 4 GB Raspberry Pi running Home Assistant ran out at 12:39 on 2026-11-09,
    with this app at 1.6 GB."""
    m = re.search(r"^MemTotal:\s+(\d+) kB", meminfo, re.M)
    gib = int(m.group(1)) / 2**20 if m else None
    if gib is None or gib >= MIN_MEMORY_GIB:
        return None
    return (f"This computer has {gib:.1f} GiB of memory; un-subscribird needs 8 GB. BioCLIP 2 and OWL-ViT use "
            "1.5 GB or more on top of everything else, so the computer may slow to a crawl or run out of memory. "
            "Use a computer with 8 GB or more; with Docker, Home Assistant can stay where it is (see the README).")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        warning = low_memory(MEMINFO.read_text())
    except OSError:
        warning = None
    if warning:
        LOG.warning(warning)
    token = os.environ.get("SUPERVISOR_TOKEN")
    if token and OPTIONS.exists():
        mqtt = mqtt_service(token)
        LOG.info("Home Assistant add-on; MQTT broker %s", "from the Supervisor" if mqtt else "from the options")
        os.environ.update(environment(json.loads(OPTIONS.read_text()), mqtt))
        Path(IMAGES).mkdir(parents=True, exist_ok=True)
        os.nice(NICE)
    os.execvp("uvicorn", ["uvicorn", "wbs.main:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers"])


if __name__ == "__main__":
    main()
