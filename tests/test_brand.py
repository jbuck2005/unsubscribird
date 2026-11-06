"""The un-subscribird look: logo and fonts ship with the app, the default name is the three-tone wordmark,
and no page asks a third party for anything."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from wbs import main
from wbs.config import Settings
from wbs.recognition import Recognizer

STATIC = Path(main.__file__).parent / "static"
TEMPLATES = Path(main.__file__).parent / "templates"


def test_brand_files_are_served():
    c = TestClient(main.app)
    for f in ("brand/favicon-64.png", "brand/mark-192.png", "brand/logo-light.png", "brand/logo-dark.png",
              "fonts/inter-latin-wght-normal.woff2", "fonts/montserrat-latin-800-normal.woff2"):
        assert c.get(f"/static/{f}").status_code == 200, f


def test_default_name_is_the_three_tone_wordmark_and_custom_names_stay_plain():
    c = TestClient(main.app)
    assert main.settings.site_name == "un-subscribird"
    for page in ("/", "/login", "/admin"):
        html = c.get(page).text
        assert ('<span class="un">un-</span><span class="sub">subscri</span><span class="bird">bird</span>'
                in html), page
        assert "<title>" in html and "un-subscribird" in html.split("<title>")[1].split("</title>")[0], page
        assert "/static/brand/favicon-64.png" in html, page
    main.settings.site_name = "Robin's Feeder"
    try:
        assert 'class="wordmark"' not in c.get("/").text
    finally:
        main.settings.site_name = "un-subscribird"


def test_no_third_party_requests_in_pages_or_styles():
    external = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import""", re.I)
    for f in [*TEMPLATES.glob("*.html"), *STATIC.glob("*.css")]:
        assert not external.search(f.read_text(encoding="utf-8")), f.name


def test_renaming_the_site_never_changes_home_assistant_entity_ids(monkeypatch):
    monkeypatch.setenv("WBS_HA_ID", "unsubscribird")
    monkeypatch.setenv("WBS_SITE_NAME", "un-subscribird")
    r = Recognizer(Settings(), main.db, lambda *a: None)
    for topic, body in [*r.discovery(), r.sighting_config(), r.species_image_config("Blue Jay")]:
        component = topic.split("/")[-4]
        if "/species_blue_jay/" in topic:   # the gallery names these image.<id>_<slug>_photo
            assert body["default_entity_id"] == "image.unsubscribird_blue_jay_photo", topic
        else:
            assert body["default_entity_id"] == f"{component}.{body['unique_id']}", topic
        assert body["default_entity_id"].split(".")[1].startswith("unsubscribird_"), topic
