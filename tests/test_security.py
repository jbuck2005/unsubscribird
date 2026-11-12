import asyncio
import io
import os
import subprocess
import time
from datetime import datetime

import pytest
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from starlette.requests import Request

from wbs import collector as col
from wbs import main
from wbs.config import settings

CRAFTED = {"Host": "x/static/?"}     # Starlette's request.url would read this as path /static/


def secure():
    os.environ["WBS_AUTH"] = "on"
    os.environ["WBS_ADMIN_PASSWORD"] = "hunter2-bird"


def teardown_function(_):
    os.environ["WBS_AUTH"] = "off"
    os.environ.pop("WBS_ADMIN_PASSWORD", None)


def anonymous():
    return TestClient(main.app, follow_redirects=False)


def logged_in():
    c = anonymous()
    assert c.post("/login", data={"password": "hunter2-bird"}).status_code == 303
    return c


def visit(trace, species, excluded=0):
    """A visit with a clip and one frame on disk."""
    when = datetime.now().replace(hour=0, minute=2, second=0, microsecond=0)
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
    d = settings.image_dir / "visits" / trace
    d.mkdir(parents=True, exist_ok=True)
    (d / "clip.mp4").write_bytes(b"clip")
    (d / "f.jpg").write_bytes(b"frame")
    (d / "other.jpg").write_bytes(b"not a frame")
    main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", f"visits/{trace}/f.jpg", 1.0, 0.5, 10, 10)
    main.db.set_visit(trace, clip=f"visits/{trace}/clip.mp4", rec_species=species, rec_source="model", rec_at=1,
                      excluded=excluded)
    return when


# ---- the login can't be talked out of by the Host header ------------------------
def test_unknown_host_is_refused():
    secure()
    c = anonymous()
    assert c.get("/api/stats", headers=CRAFTED).status_code == 400
    assert c.put("/api/settings", headers=CRAFTED, json={}).status_code == 400
    assert c.get("/api/public/day", headers={"Host": "rebound.example"}).status_code == 400
    assert c.get("/api/public/day", headers={"Host": "192.0.2.10:8095"}).status_code == 200
    assert c.get("/api/public/day", headers={"Host": "localhost:8095"}).status_code == 200


def test_login_check_ignores_the_host_header_on_its_own():
    """The same attack straight at the login check, in case the host allowlist is ever loosened."""
    secure()
    scope = {"type": "http", "method": "GET", "path": "/api/stats", "raw_path": b"/api/stats", "query_string": b"",
             "headers": [(b"host", b"x/static/?")], "server": ("192.0.2.10", 8095), "scheme": "http"}
    request = Request(scope)
    # Starlette before 1.x rebuilt request.url from this Host header, giving "/static/": what made this exploitable.
    # Newer versions ignore a malformed Host, but the login check must not rely on that.
    assert request.url.path in ("/static/", "/api/stats")

    async def nxt(_):
        return PlainTextResponse("reached the route")
    assert asyncio.run(main.require_login(request, nxt)).status_code == 401


# ---- what the public can see ------------------------------------------------------
@pytest.mark.parametrize("trace,species,excluded,public", [
    ("pub-jay", "Blue Jay", 0, True),
    ("pub-squirrel", "Squirrel", 0, True),
    ("hid-uncertain", "Uncertain", 0, False),
    ("hid-unknown", "Unknown bird", 0, False),
    ("hid-other", "Other animal", 0, False),
    ("hid-freetext", "a person holding a sign", 0, False),
    ("hid-empty", "Empty", 0, False),
    ("hid-excluded", "Blue Jay", 1, False),
])
def test_public_footage_needs_a_named_species(trace, species, excluded, public):
    secure()
    when = visit(trace, species, excluded)
    c = anonymous()
    listed = [v["trace_id"] for v in c.get(f"/api/public/day?day={when.date().isoformat()}").json()["visits"]]
    assert (trace in listed) == public
    # Any name is sent on to the clip's real one, but only after the access check: a hidden clip is a plain 404.
    assert c.get(f"/clips/{trace}/x.mp4", follow_redirects=True).status_code == (200 if public else 404)
    assert c.get(f"/img/visits/{trace}/f.jpg").status_code == (200 if public else 404)
    you = logged_in()                                     # the review pages still see everything
    assert you.get(f"/clips/{trace}/x.mp4", follow_redirects=True).status_code == 200
    assert you.get(f"/img/visits/{trace}/f.jpg").status_code == 200


def test_only_frames_are_public_under_img():
    secure()
    visit("pub-files", "Blue Jay")
    c = anonymous()
    assert c.get("/img/visits/pub-files/f.jpg").content == b"frame"
    assert c.get("/img/visits/pub-files/clip.mp4").status_code == 404     # clips go through /clips
    assert c.get("/img/visits/pub-files/other.jpg").status_code == 404
    assert logged_in().get("/img/visits/pub-files/other.jpg").status_code == 200


def test_img_stays_inside_the_image_folder():
    secure()
    outside = settings.image_dir.parent / "secret.txt"
    outside.write_text("no")
    you = logged_in()
    for path in ("/img/../secret.txt", "/img/%2e%2e/secret.txt", "/img/..%2fsecret.txt"):
        assert you.get(path).status_code == 404


# ---- MQTT input ---------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status, body=b""):
        self.status_code, self.raw = status, io.BytesIO(body)


class FakeHttp:
    def __init__(self, response):
        self.response, self.calls = response, []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return self.response


def clip_visit(trace, clip_url):
    main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": time.time() - 100, "time": "x",
                          "clip_url": clip_url})
    return main.db.one("SELECT * FROM visits WHERE trace_id=?", trace)


def collector_with(response):
    c = col.Collector(settings, main.db)
    c.http = FakeHttp(response)
    return c


def stored(trace):
    return main.db.one("SELECT * FROM visits WHERE trace_id=?", trace)


@pytest.mark.parametrize("url", ["@evil.example/x.mp4", "/local/../api/x.mp4", "/local/a.mp4?x=1", "/local/a.mp4\n",
                                 "/api/states.mp4", "http://evil.example/local/a.mp4"])
def test_clip_url_must_be_a_local_mp4(url):
    v = clip_visit(f"badurl{abs(hash(url))}", url)
    c = collector_with(FakeResponse(200))
    c.fetch_clip(v)
    assert c.http.calls == [] and "bad clip_url" in stored(v["trace_id"])["error"]


def test_clip_download_follows_no_redirects():
    v = clip_visit("redirect1", "/local/vicohome/redirect1.mp4")
    c = collector_with(FakeResponse(302))
    c.fetch_clip(v)
    url, kw = c.http.calls[0]
    assert url == f"{settings.ha_url}/local/vicohome/redirect1.mp4" and kw["allow_redirects"] is False
    assert "clip HTTP 302" in stored("redirect1")["error"]


def test_a_download_that_isnt_a_video_is_not_kept():
    v = clip_visit("notvideo", "/local/vicohome/notvideo.mp4")
    collector_with(FakeResponse(200, b'{"internal": "json"}')).fetch_clip(v)
    d = col.visit_dir(settings, "notvideo", v["ts"])
    assert not (d / "clip.mp4").exists() and not (d / "clip.part").exists()
    assert stored("notvideo")["clip"] is None and stored("notvideo")["attempts"] == 1


def test_a_real_clip_still_downloads(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(src)], check=True)
    v = clip_visit("0000000017939693", "/local/vicohome/0000000017939693.mp4")
    collector_with(FakeResponse(200, src.read_bytes())).fetch_clip(v)
    assert stored(v["trace_id"])["clip"].endswith("0000000017939693/clip.mp4")


def test_oversized_clip_is_abandoned(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "MAX_CLIP_BYTES", 10)
    with pytest.raises(RuntimeError, match="clip is over"):
        col.save_capped(io.BytesIO(b"x" * 11), tmp_path / "clip.part")


@pytest.mark.parametrize("trace", ["../../../../etc/x", "..", "a/b", "a\\b", "a.b", "a\n", "", "x" * 65, 7])
def test_bad_trace_ids_never_reach_the_filesystem(trace):
    assert not col.valid_trace(trace)
    with pytest.raises(ValueError):
        col.visit_dir(settings, trace, time.time())


def test_bad_trace_ids_are_dropped_on_arrival():
    c = col.Collector(settings, main.db)
    c.latest_image["cam"] = (b"attacker bytes", time.time())
    bad = "../../../escape"
    c.on_last("cam", {"trace_id": bad, "timestamp": time.time(), "time": "x"})
    c.on_today("cam", {"recent": [{"trace_id": bad, "time": "2026-11-06T09:00:00-05:00"}]})
    assert stored(bad) is None and "cam" not in c.latest_trace


def test_a_stored_bad_trace_id_doesnt_stop_the_queue():
    v = clip_visit("../stored", "/local/vicohome/x.mp4")
    collector_with(FakeResponse(200)).fetch_clip(v)
    assert "bad trace id" in stored("../stored")["error"]


# ---- clip retries wait out a Home Assistant restart ---------------------------------------
def test_clip_retries_back_off_for_15_minutes():
    assert col.CLIP_RETRY_AT_S[-1] == 15 * 60
    assert list(col.CLIP_RETRY_AT_S) == sorted(col.CLIP_RETRY_AT_S)
    v = {"attempts": 0, "created": 1000.0}
    assert col.clip_due(v, 1000)
    v["attempts"] = 3   # 4th try is due 40 s in
    assert not col.clip_due(v, 1039) and col.clip_due(v, 1040)
    v["attempts"] = col.MAX_CLIP_ATTEMPTS - 1   # last try at 15 min
    assert not col.clip_due(v, 1000 + 899) and col.clip_due(v, 1000 + 900)
    v["attempts"] = col.MAX_CLIP_ATTEMPTS
    assert not col.clip_due(v, 10**9)


def test_a_failed_clip_waits_for_its_next_try_then_gives_up_after_the_last():
    clip_visit("haoffline1", "/local/vicohome/haoffline1.mp4")
    c = collector_with(FakeResponse(502))
    mine = lambda: sum(url.endswith("/haoffline1.mp4") for url, _ in c.http.calls)   # other tests leave visits too
    c.process_pending()
    assert mine() == 1 and stored("haoffline1")["status"] == "new"
    c.process_pending()   # next try is 10 s after the visit arrived: not yet
    assert mine() == 1
    main.db.set_visit("haoffline1", created=time.time() - 15 * 60)   # 15 minutes later, HA still down
    for _ in range(col.MAX_CLIP_ATTEMPTS + 2):
        c.process_pending()
    assert mine() == col.MAX_CLIP_ATTEMPTS
    assert stored("haoffline1")["status"] == "failed"   # no snapshot either
