import socket

import pytest

from commercelens.core.renderer import RenderError, _route_request, render_html
from commercelens.core.url_policy import URLValidator


def public_resolver(host: str, port: int, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        )
    ]


def test_render_html_rejects_private_destinations_before_launch() -> None:
    with pytest.raises(RenderError, match="non-public address space"):
        render_html("http://127.0.0.1/admin")


def test_browser_route_blocks_private_subresources() -> None:
    class Route:
        action: str | None = None

        def abort(self, reason: str) -> None:
            self.action = f"abort:{reason}"

        def continue_(self) -> None:
            self.action = "continue"

    class Request:
        url = "http://127.0.0.1/internal-script.js"

    route = Route()
    _route_request(route, Request(), URLValidator(resolver=public_resolver))

    assert route.action == "abort:blockedbyclient"


def test_render_html_reports_missing_playwright_cleanly() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError:
        with pytest.raises(RenderError) as exc:
            render_html("https://example.com", resolver=public_resolver)
        assert "Playwright is not installed" in str(exc.value)
    else:
        pytest.skip(
            "Playwright is installed in this environment; integration rendering is not run here."
        )
