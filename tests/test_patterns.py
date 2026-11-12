import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from wbs import main, patterns
from wbs.config import Settings

NOW = datetime(2025, 6, 18, 12, 30).timestamp()      # a Wednesday; no other test uses 2025


def visit(trace, when, species, also=None):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    fid = main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", None, 1.0, 0.5, 10, 10)
    main.db.set_visit(trace, rec_species=species, rec_source="model", rec_conf=0.9, rec_at=1)
    if also:
        main.db.set_label(trace, species, [fid], None, "confirmed", None, also)


def test_visits_by_hour_and_week():
    d = datetime.fromtimestamp(NOW)
    visit("pt1", d.replace(hour=8), "Blue Jay")
    visit("pt2", d.replace(hour=8, minute=40), "Blue Jay", also=["Downy Woodpecker"])
    visit("pt3", d.replace(hour=11) - timedelta(days=9), "Blue Jay")       # Monday of the week before
    visit("pt4", d.replace(hour=9), "Empty")
    h = patterns.by_hour(main.db, 30, NOW)
    assert h["counts"]["Blue Jay"][8] == 2 and h["counts"]["Blue Jay"][11] == 1
    assert h["counts"]["Downy Woodpecker"][8] == 1 and "Empty" not in h["counts"]
    assert h["species"][0] == "Blue Jay"                                   # busiest first
    w = patterns.by_week(main.db, 4, NOW)
    assert w["weeks"][-1] == "2025-06-16" and w["weeks"][0] == "2025-05-26"   # Mondays
    assert w["counts"]["Blue Jay"][-2:] == [1, 2]


def test_birds_per_hour_by_temperature():
    d = datetime.fromtimestamp(NOW).replace(hour=0, minute=0) - timedelta(days=200)   # away from the other visits
    with main.db.tx() as c:
        for k in range(0, 24 * 6):                                         # one day of samples every 10 minutes
            ts = (d + timedelta(minutes=10 * k)).timestamp()
            c.execute("INSERT INTO weather(ts, temp, unit) VALUES (?,?,?)", (ts, -12.0 if k < 72 else 3.0, "°C"))
    visit("ptt1", d.replace(hour=8), "Blue Jay")                           # -12 °C
    visit("ptt2", d.replace(hour=8, minute=20), "Blue Jay")
    visit("ptt3", d.replace(hour=14), "Blue Jay")                          # 3 °C
    t = patterns.by_temperature(main.db, 1, d.timestamp() + 86400)
    bands = {b["from"]: b for b in t["bands"]}
    assert t["unit"] == "°C" and t["busy_hours"] == [8, 14] and t["samples"] == 144 and t["latest"]["temp"] == 3.0
    assert (bands[-15]["visits"], bands[-15]["hours"]) == (2, 1.0) and bands[0]["visits"] == 1
    assert patterns.by_temperature(main.db, 1, NOW - 86400 * 300) is None   # no samples then


def test_current_temperature_only_while_fresh():
    t0 = datetime(2025, 7, 1, 12, 0).timestamp()                         # away from the other tests' samples
    with main.db.tx() as c:
        c.execute("INSERT INTO weather(ts, temp, unit) VALUES (?,?,?)", (t0, 21.6, "°C"))
    assert patterns.current(main.db, t0 + 600) == {"temp": 22, "unit": "°C", "ts": t0}
    assert patterns.current(main.db, t0 + 3 * 3600) is None               # sensor stopped: show nothing


def test_feeder_quiet_when_a_busy_time_goes_silent():
    now = datetime(2025, 3, 20, 13, 0).timestamp()
    base = datetime.fromtimestamp(now)
    for day in range(1, 15):                                               # the last two weeks: busy late morning
        for m in (0, 10, 20, 30, 40, 50):
            visit(f"fq{day}-{m}", base - timedelta(days=day, hours=2, minutes=-m), "Black-capped Chickadee")
    q = patterns.feeder_quiet(main.db, 3, now)
    assert q["quiet"] and q["expected"] == 6.0 and q["recent"] == 0
    visit("fq-now", base - timedelta(minutes=30), "Black-capped Chickadee")
    assert not patterns.feeder_quiet(main.db, 3, now)["quiet"]
    assert patterns.feeder_quiet(main.db, 0, now) == {"quiet": False, "enabled": False}


class FakeHttp:
    def __init__(self, body):
        self.body, self.calls = body, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        body = self.body

        class R:
            def raise_for_status(self):
                pass

            def json(self):
                return body
        return R()


def test_weather_sampler_reads_a_sensor_or_a_weather_entity(monkeypatch):
    monkeypatch.setenv("UNSUB_TEMP_SENSOR", "sensor.outdoor")
    s = Settings()
    w = patterns.WeatherSampler(s, main.db, "http://ha.example:8123/api", "tok")
    w.http = FakeHttp({"state": "-4.5", "attributes": {"unit_of_measurement": "°C"}})
    assert w.read() == (-4.5, "°C")
    url, kw = w.http.calls[0]
    assert url == "http://ha.example:8123/api/states/sensor.outdoor" and kw["headers"] == {"Authorization": "Bearer tok"}
    s.temp_sensor = "weather.home"
    w.http = FakeHttp({"state": "sunny", "attributes": {"temperature": 21, "temperature_unit": "°F"}})
    assert w.read() == (21.0, "°F")
    w.http = FakeHttp({"state": "unavailable", "attributes": {}})
    s.temp_sensor = "sensor.outdoor"
    w.sample()                                                             # logged, not raised
    assert w.last_error
    assert patterns.WeatherSampler(s, main.db, "http://x/api", "").read() is None   # no token: off


def test_patterns_api_and_ha_feeder_sensor():
    r = TestClient(main.app).get("/api/patterns?days=7").json()
    assert {"hours", "weeks", "temperature", "temp_sensor", "feeder"} <= set(r)
    assert TestClient(main.app).get("/api/patterns?days=0").status_code == 400
    sent = []
    rec = main.Recognizer(Settings(), main.db, lambda t, p, retain: sent.append((t, p)))
    topic, body = next(c for c in rec.discovery() if "/feeder_quiet/" in c[0])
    assert topic == "homeassistant/binary_sensor/unsubscribird/feeder_quiet/config" and body["device_class"] == "problem"
    rec.publish_feeder(NOW)
    rec.publish_feeder(NOW + 60)                                           # unchanged: not sent again within the hour
    assert [t for t, _ in sent] == ["unsubscribird/feeder"] and "quiet" in json.loads(sent[0][1])
