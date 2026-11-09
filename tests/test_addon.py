"""As a Home Assistant add-on: the sidebar (Ingress) opens every page, but only for the Supervisor."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wbs import __version__, main, start

ROOT = Path(__file__).parent.parent
INGRESS = {"X-Ingress-Path": "/api/hassio_ingress/AbC-12_x", "Host": "homeassistant.local:8123"}


def client(peer=main.INGRESS_PEER):
    async def app(scope, receive, send):    # TestClient always says the request came from "testclient"
        scope["client"] = (peer, 40000)
        await main.app(scope, receive, send)
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def addon(monkeypatch):
    monkeypatch.setenv("WBS_AUTH", "on")
    monkeypatch.setenv("WBS_ADMIN_PASSWORD", "hunter2-bird")
    monkeypatch.setattr(main.settings, "ingress", True)


def test_the_sidebar_opens_settings_with_the_ha_login(addon):
    r = client().get("/admin/settings", headers=INGRESS)
    assert r.status_code == 200 and 'href="/api/hassio_ingress/AbC-12_x/static/' in r.text
    assert client().get("/api/stats", headers=INGRESS).status_code == 200


def test_redirects_stay_inside_the_sidebar(addon):
    r = client().get("/?visit=abc", headers=INGRESS)
    assert r.headers["location"] == "/api/hassio_ingress/AbC-12_x/admin?visit=abc"


def test_only_the_supervisor_gets_in_that_way(addon):
    other = client("172.30.33.5")       # another add-on, or anyone on a mapped port
    assert other.get("/api/stats", headers=INGRESS).status_code == 400       # unknown host
    r = other.get("/admin", headers={**INGRESS, "Host": "localhost"})
    assert r.status_code == 303 and r.headers["location"].startswith("/login")   # no prefix, and a login
    assert other.get("/api/stats", headers={"X-Forwarded-For": main.INGRESS_PEER, "Host": "localhost"}).status_code == 401


def test_without_the_add_on_the_supervisor_address_is_nothing_special(monkeypatch):
    monkeypatch.setenv("WBS_AUTH", "on")
    monkeypatch.setenv("WBS_ADMIN_PASSWORD", "hunter2-bird")
    assert not main.settings.ingress
    assert client().get("/api/stats", headers=INGRESS).status_code == 400
    assert client().get("/api/stats", headers={"Host": "localhost"}).status_code == 401


def test_options_become_settings():
    env = start.environment({"site_name": "Robin's Feeder", "lmstudio_url": "http://192.0.2.30:1234",
                             "embed_threads": 2, "host": "", "mqtt_host": None},
                            {"host": "core-mosquitto", "port": 1883, "username": "addons", "password": "pw"})
    assert env["WBS_INGRESS"] == "true" and env["WBS_IMAGE_DIR"] == "/media/unsubscribird"
    assert env["WBS_SITE_NAME"] == "Robin's Feeder" and env["WBS_EMBED_THREADS"] == "2"
    assert env["WBS_LMSTUDIO_URL"] == "http://192.0.2.30:1234" and "WBS_HOST" not in env
    assert (env["WBS_MQTT_HOST"], env["WBS_MQTT_USER"], env["WBS_MQTT_PASSWORD"]) == ("core-mosquitto", "addons", "pw")


def test_an_mqtt_option_beats_the_supervisor_broker():
    env = start.environment({"mqtt_host": "192.0.2.40", "mqtt_port": 8883}, {"host": "core-mosquitto", "port": 1883})
    assert (env["WBS_MQTT_HOST"], env["WBS_MQTT_PORT"]) == ("192.0.2.40", "8883")


def test_every_option_has_a_setting_and_a_label():
    config = (ROOT / "addon/config.yaml").read_text()
    schema = re.search(r"^schema:\n((?:  .*\n)+)", config, re.M).group(1)
    options = set(re.findall(r"^  (\w+):", schema, re.M))
    labels = set(re.findall(r"^  (\w+):\n    name:", (ROOT / "addon/translations/en.yaml").read_text(), re.M))
    assert options == set(start.OPTION_ENV) == labels


def test_the_add_on_version_is_the_app_version():
    config = (ROOT / "addon/config.yaml").read_text()
    assert re.search(r'^version: "(.+)"', config, re.M).group(1) == __version__
    assert f"## {__version__}" in (ROOT / "addon/CHANGELOG.md").read_text()
