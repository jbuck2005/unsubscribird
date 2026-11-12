"""Behind a proxy at /birds/: every link, redirect and cookie carries the prefix. Reached directly, none do."""
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wbs import main

STATIC = Path(main.HERE) / "static"
BIRDS = {"X-Forwarded-Prefix": "/birds"}
PAGES = ["/", "/collection", "/login", "/admin", "/admin/dataset", "/admin/model", "/admin/patterns", "/admin/gallery", "/admin/status",
         "/admin/settings"]
LINK = re.compile(r'(?:href|src|action)="(/[^"]*)"')


def client():
    return TestClient(main.app, follow_redirects=False)


def teardown_function(_):
    os.environ["WBS_AUTH"] = "off"
    os.environ.pop("WBS_ADMIN_PASSWORD", None)


@pytest.mark.parametrize("page", PAGES)
def test_every_link_on_every_page_has_the_prefix(page):
    html = client().get(page, headers=BIRDS).text
    links = LINK.findall(html)
    assert links and all(link.startswith("/birds/") for link in links), links
    assert 'data-base="/birds"' in html


@pytest.mark.parametrize("page", PAGES)
def test_no_prefix_when_reached_directly(page):
    html = client().get(page).text
    assert not any(link.startswith("/birds") for link in LINK.findall(html)) and 'data-base=""' in html


@pytest.mark.parametrize("path,target", [("/?visit=abc", "/birds/admin?visit=abc"), ("/gallery?species=Blue", "/birds/?species=Blue"),
                                         ("/dataset", "/birds/admin/dataset"), ("/logout", "/birds/")])
def test_redirects_keep_the_prefix(path, target):
    assert client().get(path, headers=BIRDS).headers["location"] == target


def test_login_keeps_the_prefix_and_scopes_the_cookie():
    os.environ.update(WBS_AUTH="on", WBS_ADMIN_PASSWORD="hunter2-bird")
    c = client()
    r = c.get("/admin/model", headers=BIRDS)
    assert r.headers["location"] == "/birds/login?next=/admin/model"
    assert c.get("/api/stats", headers=BIRDS).status_code == 401
    r = c.post("/login", data={"password": "hunter2-bird", "next": "/admin/model"}, headers=BIRDS)
    assert r.headers["location"] == "/birds/admin/model"
    assert "path=/birds" in r.headers["set-cookie"].lower()


def test_logout_clears_the_cookie_at_both_paths():
    cookies = client().get("/logout", headers=BIRDS).headers.get_list("set-cookie")
    assert any("Path=/birds" in c for c in cookies) and any("Path=/;" in c or c.endswith("Path=/") for c in cookies)


@pytest.mark.parametrize("bad", ["//evil.example", "/a b", "https://evil.example", "/x\"><script>", "/..", "birds"])
def test_a_bad_prefix_is_ignored(bad):
    r = client().get("/logout", headers={"X-Forwarded-Prefix": bad})
    assert r.headers["location"] == "/"
    assert 'data-base=""' in client().get("/", headers={"X-Forwarded-Prefix": bad}).text


@pytest.mark.parametrize("name", ["app.js", "kids.js", "collection.js"])
def test_scripts_build_no_bare_root_links(name):
    js = (STATIC / name).read_text()
    assert not re.search(r"""(?:src|href|data-full|action)=["']/""", js)
    assert not re.search(r"""(?<![-\w])(?:src|href)="\$\{esc\(""", js)   # a server path needs BASE (data-src: added at load)
    assert not re.search(r"""fetch\(\s*[`"']/""", js)
