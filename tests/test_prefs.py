import pytest
from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings
from wbs.prefs import PREFS, Prefs


def teardown_function(_):
    main.prefs.save({p.key: None for p in PREFS})


def value(body, key):
    return next(p for p in body["prefs"] if p["key"] == key)


def test_save_applies_at_once_and_survives_a_restart():
    c = TestClient(main.app)
    default = settings.clip_skip_s
    r = c.put("/api/settings", json={"clip_skip_s": 4, "kids_sort": "bird", "auto_train": False, "region": "Perth"})
    assert r.status_code == 200 and value(r.json(), "clip_skip_s")["saved"]
    assert settings.clip_skip_s == 4 and settings.kids_sort == "bird" and settings.auto_train is False
    assert settings.region == "Perth"
    assert 'data-sort="bird"' in c.get("/").text              # pages pick it up straight away

    settings.clip_skip_s = default                           # a fresh start: env default, then the database
    settings.kids_sort = "new"
    Prefs(settings, main.db)
    assert settings.kids_sort == "bird" and settings.clip_skip_s == 4


def test_reset_returns_to_the_default():
    c = TestClient(main.app)
    default = settings.ha_model_confidence
    c.put("/api/settings", json={"ha_model_confidence": 0.9})
    body = c.put("/api/settings", json={"ha_model_confidence": None}).json()
    assert settings.ha_model_confidence == default and not value(body, "ha_model_confidence")["saved"]
    body = c.put("/api/settings", json={"ha_model_confidence": default}).json()    # saving the default stores nothing
    assert not value(body, "ha_model_confidence")["saved"]


@pytest.mark.parametrize("bad", [
    {"auto_train_hour": 24}, {"auto_train_hour": 1.5}, {"ha_model_confidence": 2}, {"clip_skip_s": ""},
    {"clip_skip_s": "abc"}, {"sun_lat": 91}, {"kids_sort": "random"}, {"auto_train": "yes"}, {"region": " "},
    {"no_such_setting": 1}, {"mqtt_password": "x"},
])
def test_bad_values_are_refused(bad):
    r = TestClient(main.app).put("/api/settings", json=bad)
    assert r.status_code == 400 and r.json()["detail"]


def test_one_bad_value_saves_nothing():
    default = settings.frames_per_visit
    r = TestClient(main.app).put("/api/settings", json={"frames_per_visit": 2, "auto_train_hour": 99})
    assert r.status_code == 400 and settings.frames_per_visit == default
    assert "frames_per_visit" not in main.prefs.saved()


def test_pausing_stops_lm_studio_and_resuming_starts_it(monkeypatch):
    lm = main.prelabeler.lm
    calls = []
    monkeypatch.setattr(lm, "pick_model", lambda: calls.append(1) or "model")
    main.prefs.save({"prelabel_paused": True})
    assert main.prelabeler.next_model() is None
    assert main.prelabeler.label_frame("x", None) is None
    assert calls == [] and lm.status.startswith("paused")
    main.prefs.save({"prelabel_paused": False})
    assert main.prelabeler.next_model() == "model" and calls == [1]


def test_the_pause_switch_is_on_the_settings_api():
    body = TestClient(main.app).get("/api/settings").json()
    assert value(body, "prelabel_paused")["kind"] == "bool"
    assert value(TestClient(main.app).put("/api/settings", json={"prelabel_paused": True}).json(), "prelabel_paused")["value"] is True


def test_every_pref_is_a_real_setting_and_no_secrets():
    for p in PREFS:
        assert hasattr(settings, p.key)
        assert not any(w in p.key for w in ("password", "secret", "token"))


def test_settings_need_the_login(monkeypatch):
    monkeypatch.setenv("WBS_AUTH", "on")
    monkeypatch.setenv("WBS_ADMIN_PASSWORD", "x")
    c = TestClient(main.app, follow_redirects=False)
    assert c.get("/api/settings").status_code == 401
    assert c.put("/api/settings", json={"clip_skip_s": 1}).status_code == 401
    assert c.get("/admin/settings").status_code == 303


def test_every_pref_can_be_set_from_env():
    """.env is the starting value and fallback, but only if the compose file passes it to the container."""
    import re
    from pathlib import Path
    root = Path(__file__).parent.parent
    config = (root / "app/wbs/config.py").read_text()
    compose = (root / "deploy/docker-compose.yaml").read_text()
    example = (root / "deploy/.env.example").read_text()
    for p in PREFS:
        env = re.search(rf'^\s+{p.key}: .*_env\("(WBS_\w+)"', config, re.M)
        assert env, f"{p.key} doesn't read an env variable"
        assert f"{env[1]}: ${{{env[1]}:-" in compose, f"{env[1]} isn't in docker-compose.yaml"
        assert f"\n{env[1]}=" in example, f"{env[1]} isn't in .env.example"
