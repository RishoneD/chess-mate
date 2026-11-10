"""Checks for the installable wrapper in docs/ (served by GitHub Pages)."""

import json
import re
from pathlib import Path

from PIL import Image

DOCS = Path(__file__).resolve().parent.parent / "docs"
APP_URL = "https://chess-mate.streamlit.app/?embed=true"


def _manifest() -> dict:
    return json.loads((DOCS / "manifest.webmanifest").read_text(encoding="utf-8"))


def test_manifest_fields():
    m = _manifest()
    assert m["name"] == "Chess-Mate"
    assert m["short_name"] == "Chess-Mate"
    assert len(m["short_name"]) <= 12
    assert m["display"] == "standalone"
    # Relative start_url and scope, so the site works under /chess-mate/ on GitHub Pages.
    assert m["start_url"] == "./"
    assert m["scope"] == "./"
    assert re.fullmatch(r"#[0-9a-fA-F]{6}", m["theme_color"])


def test_manifest_icons_exist_with_declared_size():
    icons = _manifest()["icons"]
    sizes = set()
    purposes = set()
    for icon in icons:
        path = DOCS / icon["src"]
        assert path.exists(), icon["src"]
        w, h = (int(x) for x in icon["sizes"].split("x"))
        with Image.open(path) as img:
            assert img.size == (w, h), icon["src"]
            assert img.format == "PNG"
        sizes.add(w)
        purposes.add(icon.get("purpose", "any"))
    assert {192, 512} <= sizes
    assert {"any", "maskable"} <= purposes


def test_index_links_manifest_and_embeds_app():
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="manifest.webmanifest">' in html
    assert f'src="{APP_URL}"' in html
    assert "clipboard-write" in html
    assert 'register("sw.js")' in html
    assert (DOCS / "sw.js").exists()
    assert (DOCS / "apple-touch-icon.png").exists()
