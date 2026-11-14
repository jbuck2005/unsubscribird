from pathlib import Path

from fastapi.testclient import TestClient
from wbs import main


def test_admin_pages_have_a_phone_menu():
    c = TestClient(main.app)
    for path, name in (("/admin", "Review"), ("/admin/status", "Status"), ("/admin/settings", "Settings")):
        t = c.get(path).text
        assert 'class="navtoggle"' in t and 'aria-controls="mainnav"' in t and 'id="mainnav"' in t
        assert f'<span class="navpage">{name}</span>' in t   # the button names the page you're on
        nav = t.split('id="mainnav"', 1)[1].split("</nav>", 1)[0]
        assert 'class="ver"' in nav                           # the version sits in the menu, not beside it


def test_phone_styles_fold_the_clutter():
    css = (Path(main.__file__).parent / "static" / "style.css").read_text()
    phone = css.split("@media (max-width: 640px)", 1)[1]
    for rule in (".navtoggle { display: inline-flex", "header.open nav { display: flex",
                 ".tabs { display: flex; flex-wrap: nowrap", ".keys { display: none",
                 ".preds .more { display: none", ".frames { order: 1"):
        assert rule in phone, rule
    assert ".navtoggle { display: none; }" in css.split("@media", 1)[0]   # wide screens keep the plain nav
