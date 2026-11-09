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


def test_switches_become_true_or_false():
    assert start.environment({"detect": False}, {})["WBS_DETECT"] == "false"
    assert start.environment({"detect": True}, {})["WBS_DETECT"] == "true"


PI_4GB = "MemTotal:        3884332 kB\nMemFree:          760000 kB\n"
PC_8GB = "MemTotal:        7995684 kB\nMemFree:         4000000 kB\n"


def test_too_little_memory_gets_a_warning():
    warning = start.low_memory(PI_4GB)
    assert warning and "3.7 GiB" in warning and "8 GB" in warning
    assert start.low_memory(PC_8GB) is None
    assert start.low_memory("") is None       # can't tell: say nothing


def test_the_warning_reaches_the_log(tmp_path, monkeypatch, caplog):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(PI_4GB)
    monkeypatch.setattr(start, "MEMINFO", meminfo)
    monkeypatch.setattr(start.os, "environ", {})
    monkeypatch.setattr(start.os, "execvp", lambda f, args: None)
    start.main()
    assert any(r.levelname == "WARNING" and "GiB of memory" in r.message for r in caplog.records)


def test_the_add_on_gives_way_to_home_assistant(tmp_path, monkeypatch):
    options = tmp_path / "options.json"
    options.write_text('{"site_name": "un-subscribird", "detect": false}')
    calls = []
    monkeypatch.setattr(start, "MEMINFO", tmp_path / "missing")
    monkeypatch.setattr(start, "OPTIONS", options)
    monkeypatch.setattr(start, "IMAGES", str(tmp_path / "media"))
    monkeypatch.setattr(start, "mqtt_service", lambda token: {})
    monkeypatch.setattr(start.os, "environ", {"SUPERVISOR_TOKEN": "t"})
    monkeypatch.setattr(start.os, "nice", lambda n: calls.append(("nice", n)), raising=False)
    monkeypatch.setattr(start.os, "execvp", lambda f, args: calls.append(("exec", f)))
    start.main()
    assert calls == [("nice", start.NICE), ("exec", "uvicorn")] and start.NICE >= 10
    assert start.os.environ["WBS_DETECT"] == "false"


def test_outside_an_add_on_nothing_changes(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(start, "MEMINFO", tmp_path / "missing")
    monkeypatch.setattr(start.os, "environ", {})
    monkeypatch.setattr(start.os, "nice", lambda n: calls.append("nice"), raising=False)
    monkeypatch.setattr(start.os, "execvp", lambda f, args: calls.append(f))
    start.main()
    assert calls == ["uvicorn"] and start.os.environ == {}


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
