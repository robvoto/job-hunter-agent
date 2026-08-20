"""Click-test: the desktop sign-in screen fits the viewport vertically."""

from __future__ import annotations


def test_desktop_login_has_no_vertical_scroll(anon_page):
    anon_page.set_viewport_size({"width": 1644, "height": 1083})
    anon_page.goto("/login")

    document_height = anon_page.evaluate("document.scrollingElement.scrollHeight")
    viewport_height = anon_page.evaluate("window.innerHeight")

    assert document_height == viewport_height
