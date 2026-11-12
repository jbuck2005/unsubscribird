"""The repo is public: nothing specific to one home belongs in it, and a stranger's .env has to be enough."""
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wbs import main
from wbs.config import Settings
from wbs.prelabel import LMStudio

ROOT = Path(__file__).parent.parent
# Common leaks, plus your own words: UNSUB_PRIVATE_WORDS="word|other word" when you run the tests. It stays out of the repo.
PRIVATE = re.compile("|".join(filter(None, (r"10\.0\.0\.\d|/home/\w+/|pixel_\d", os.environ.get("UNSUB_PRIVATE_WORDS")))), re.I)
SKIP = {".git", "__pycache__", ".pytest_cache"}


def test_nothing_home_specific_in_the_repo():
    found = []
    for f in ROOT.rglob("*"):
        if f.is_dir() or SKIP & set(f.parts) or f.name in (".env", Path(__file__).name):
            continue
        found += [f"{f.relative_to(ROOT)}:{n}" for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1)
                  if PRIVATE.search(line)]
    assert not found


def test_the_site_name_comes_from_settings():
    main.settings.site_name = "Robin's Feeder"
    try:
        for page in ("/", "/login", "/admin"):
            assert "Robin&#39;s Feeder" in TestClient(main.app).get(page).text
    finally:
        main.settings.site_name = "un-subscribird"


def test_home_assistant_ids_come_from_settings(monkeypatch):
    from wbs.recognition import Recognizer
    monkeypatch.setenv("UNSUB_HA_ID", "my_feeder")
    monkeypatch.setenv("UNSUB_SITE_NAME", "My Feeder")
    configs = Recognizer(Settings(), main.db, lambda *a: None).discovery()
    assert configs and all("/my_feeder/" in t and b["unique_id"].startswith("my_feeder_") for t, b in configs)
    assert configs[0][1]["device"]["identifiers"] == ["my_feeder"] and configs[0][1]["device"]["name"] == "My Feeder"


def test_the_gallery_finds_each_species_photo(monkeypatch):
    """The gallery names image.<id>_<slug>_photo, so a new species must register under that id."""
    from wbs.recognition import Recognizer
    monkeypatch.setenv("UNSUB_HA_ID", "my_feeder")
    _, body = Recognizer(Settings(), main.db, lambda *a: None).species_image_config("Blue Jay")
    assert body["default_entity_id"] == "image.my_feeder_blue_jay_photo"
    assert body["unique_id"] == "my_feeder_species_blue_jay"


def test_example_env_has_no_credentials():
    example = (ROOT / "deploy/.env.example").read_text()
    for key in ("UNSUB_MQTT_USER", "UNSUB_MQTT_PASSWORD", "UNSUB_ADMIN_PASSWORD", "UNSUB_HA_TOKEN"):
        assert f"\n{key}=\n" in example


def test_every_compose_variable_is_in_the_example():
    compose = (ROOT / "deploy/docker-compose.yaml").read_text()
    example = (ROOT / "deploy/.env.example").read_text()
    for var in set(re.findall(r"\$\{(\w+)", compose)) - {v for v in re.findall(r"\$\{(WBS_\w+)", compose)}:
        assert re.search(rf"^{var}=", example, re.M), var
    assert "WBS_" not in example                          # old names: only as fallbacks in the compose file


def test_old_wbs_names_still_work(monkeypatch):
    """0.29.0 renamed WBS_ to UNSUB_. An old .env must keep working: in the app, and through the compose file."""
    from wbs import config
    monkeypatch.delenv("UNSUB_SITE_NAME", raising=False)
    monkeypatch.setenv("WBS_SITE_NAME", "Old Name")
    monkeypatch.setenv("WBS_MQTT_PORT", "1999")
    monkeypatch.setenv("UNSUB_MQTT_PORT", "1888")          # both set: the new name wins
    config.OLD_NAMES_USED.clear()
    s = Settings()
    assert (s.site_name, s.mqtt_port) == ("Old Name", 1888) and config.OLD_NAMES_USED == {"WBS_SITE_NAME"}
    compose = (ROOT / "deploy/docker-compose.yaml").read_text()
    for new in set(re.findall(r"\$\{(UNSUB_\w+)", compose)):
        assert f"${{{new}:-${{WBS_{new[6:]}" in compose, f"{new} has no WBS_ fallback in the compose file"
    # Portainer evaluates a ":?" even inside a fallback that isn't used, and then creates no container (2026-11-12).
    assert not re.search(r"\$\{WBS_\w+:\?", compose)


def hosts(monkeypatch, **env):
    for k in ("UNSUB_MQTT_HOST", "UNSUB_HA_URL", "UNSUB_LMSTUDIO_URL", "UNSUB_PUBLIC_URL", "UNSUB_AI_HOST", "UNSUB_PORT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return Settings()


def test_three_hosts_make_the_urls(monkeypatch):
    s = hosts(monkeypatch, UNSUB_HOST="192.0.2.1", UNSUB_HA_HOST="192.0.2.2", UNSUB_AI_HOST="192.0.2.3")
    assert s.public_url == "http://192.0.2.1:8095"
    assert s.ha_url == "http://192.0.2.2:8123" and s.mqtt_host == "192.0.2.2"
    assert s.lmstudio_url == "http://192.0.2.3:1234"


def test_a_setting_beats_the_host(monkeypatch):
    s = hosts(monkeypatch, UNSUB_HOST="192.0.2.1", UNSUB_HA_HOST="192.0.2.2", UNSUB_MQTT_HOST="192.0.2.9",
              UNSUB_PUBLIC_URL="https://birds.example/", UNSUB_HA_URL="https://ha.example/")
    assert s.mqtt_host == "192.0.2.9" and s.ha_url == "https://ha.example" and s.public_url == "https://birds.example"
    assert {"192.0.2.1", "birds.example", "localhost"} <= set(s.allowed_hosts)   # the host works whatever the URL


def test_lm_studio_is_optional(monkeypatch):
    s = hosts(monkeypatch, UNSUB_HOST="192.0.2.1")
    assert s.lmstudio_url == ""
    lm = LMStudio(s)
    assert lm.pick_model() is None and lm.status.startswith("off")


@pytest.mark.parametrize("headers,secure", [({"X-Forwarded-Proto": "https"}, True), ({}, False)])
def test_login_cookie_is_secure_over_https(monkeypatch, headers, secure):
    monkeypatch.setenv("UNSUB_AUTH", "on")
    monkeypatch.setenv("UNSUB_ADMIN_PASSWORD", "hunter2-bird")
    r = TestClient(main.app, follow_redirects=False).post("/login", data={"password": "hunter2-bird"}, headers=headers)
    assert r.status_code == 303 and ("secure" in r.headers["set-cookie"].lower()) is secure
