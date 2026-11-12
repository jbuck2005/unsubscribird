import os
import time
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import settings


def secure(password="hunter2-bird"):
    os.environ["UNSUB_AUTH"] = "on"
    os.environ["UNSUB_ADMIN_PASSWORD"] = password


def teardown_function(_):
    os.environ["UNSUB_AUTH"] = "off"
    os.environ.pop("UNSUB_ADMIN_PASSWORD", None)


def test_settings_need_login_but_the_kids_page_does_not():
    secure()
    c = TestClient(main.app, follow_redirects=False)
    for path in ("/admin", "/admin/dataset", "/admin/model", "/admin/patterns", "/admin/gallery", "/admin/status"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"].startswith("/login?next=")
    assert c.get("/api/visits").status_code == 401
    assert c.post("/api/model/train").status_code == 401
    assert c.post("/api/visits/x/label", json={"species": "Blue Jay", "frame_ids": [1]}).status_code == 401
    assert c.get("/").status_code == 200 and "Who came to the feeder" in c.get("/").text
    assert c.get("/api/public/day").status_code == 200
    assert c.get("/static/kids.js").status_code == 200
    assert c.get("/login").status_code == 200


def test_login_cookie_and_logout():
    secure()
    c = TestClient(main.app, follow_redirects=False)
    bad = c.post("/login", data={"password": "nope", "next": "/admin/model"})
    assert bad.status_code == 401 and "main.auth" not in bad.text
    ok = c.post("/login", data={"password": "hunter2-bird", "next": "/admin/model"})
    assert ok.status_code == 303 and ok.headers["location"] == "/admin/model"
    assert c.get("/admin/model").status_code == 200 and c.get("/api/stats").status_code == 200
    evil = c.post("/login", data={"password": "hunter2-bird", "next": "//evil.example"})
    assert evil.headers["location"] == "/admin"                         # no off-site redirect
    c.get("/logout")
    c.cookies.clear()
    assert c.get("/api/stats").status_code == 401


def test_cookie_signature_and_expiry():
    a = main.auth
    good = a.make_cookie()
    assert a.valid(good)
    assert not a.valid(good[:-4] + "AAAA")                              # tampered
    assert not a.valid(a.make_cookie(now=time.time() - 31 * 86400))     # expired
    assert not a.valid("garbage") and not a.valid(None)


def test_no_password_means_locked():
    os.environ["UNSUB_AUTH"] = "on"
    os.environ.pop("UNSUB_ADMIN_PASSWORD", None)
    c = TestClient(main.app, follow_redirects=False)
    assert "isn't set up yet" in c.get("/login").text
    assert c.post("/login", data={"password": "", "next": "/admin"}).status_code == 401


def test_old_links_redirect():
    c = TestClient(main.app, follow_redirects=False)
    assert c.get("/?visit=abc").headers["location"] == "/admin?visit=abc"
    assert c.get("/gallery?species=Blue%20Jay").headers["location"] == "/?species=Blue%20Jay"
    assert c.get("/dataset").headers["location"] == "/admin/dataset"


def test_public_day_lists_bird_clips_newest_first():
    # Early today (not noon: before noon that would be "the future" and the newest visit for other tests).
    noon = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0)
    def mk(trace, when, species):
        main.db.upsert_visit({"trace_id": trace, "serial": "cam", "timestamp": when.timestamp(), "time": when.isoformat()})
        p = settings.image_dir / "visits" / trace
        p.mkdir(parents=True, exist_ok=True)
        main.db.add_frame(trace, "clip", f"visits/{trace}/f.jpg", f"visits/{trace}/f_thumb.jpg", 1.0, 0.5, 10, 10)
        main.db.set_visit(trace, clip=f"visits/{trace}/clip.mp4", rec_species=species, rec_source="model", rec_at=1)
    mk("kid1", noon, "Blue Jay")
    mk("kid2", noon + timedelta(minutes=10), "Uncertain")
    main.db.set_label("kid2", "Unknown bird", [], None, "confirmed")     # a human looked: a mystery bird is fine
    mk("kid3", noon + timedelta(minutes=20), "Empty")
    d = TestClient(main.app).get(f"/api/public/day?day={noon.date().isoformat()}").json()
    mine = [v for v in d["visits"] if v["trace_id"].startswith("kid")]
    assert [v["trace_id"] for v in mine] == ["kid2", "kid1"]             # newest first, no Empty
    assert mine[0]["species"] == "Mystery bird" and mine[1]["clip"].endswith("_blue-jay.mp4")
    assert mine[1]["poster"] == "/img/visits/kid1/f_thumb.jpg" and mine[1]["dot"]
    # Somewhere to read about each species; none for a mystery bird.
    assert d["about"]["Blue Jay"] == {"Wikipedia": "https://en.wikipedia.org/wiki/Cyanocitta_cristata",
                                      "All About Birds": "https://www.allaboutbirds.org/guide/Blue_Jay"}
    assert "Mystery bird" not in d["about"]


def test_pages_carry_the_theme_script_and_location():
    c = TestClient(main.app)
    for path in ("/", "/login", "/admin/model"):
        t = c.get(path).text
        assert "/static/theme.js" in t and f'data-lat="{settings.sun_lat}"' in t and 'id="theme-toggle"' in t or path == "/login"
    assert c.get("/static/theme.js").status_code == 200
