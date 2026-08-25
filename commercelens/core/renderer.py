from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from commercelens.core.url_policy import Resolver, URLPolicy, URLPolicyError, URLValidator


class RenderError(RuntimeError):
    """Raised when browser rendering fails or Playwright is unavailable."""


@dataclass(slots=True)
class RenderedPage:
    url: str
    html: str
    final_url: str | None = None
    screenshot_path: str | None = None
    html_snapshot_path: str | None = None


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RenderError(
            "Playwright is not installed. Install browser support with "
            "`pip install -e .[browser]` and then run `playwright install chromium`."
        ) from exc
    return sync_playwright


def render_html(
    url: str,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
    user_agent: str | None = None,
    screenshot_path: str | Path | None = None,
    html_snapshot_path: str | Path | None = None,
    *,
    policy: URLPolicy | None = None,
    resolver: Resolver = socket.getaddrinfo,
) -> RenderedPage:
    """Render a JavaScript-heavy page with Playwright and return final HTML.

    Playwright is optional. This function imports it lazily so CommerceLens remains
    lightweight for static HTML extraction.
    """
    validator = URLValidator(policy=policy, resolver=resolver)
    try:
        safe_url = validator.validate(url)
    except URLPolicyError as exc:
        raise RenderError(str(exc)) from exc

    sync_playwright = _import_playwright()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs = {}
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        context = browser.new_context(**context_kwargs)
        context.route("**/*", lambda route, request: _route_request(route, request, validator))
        page = context.new_page()

        try:
            page.goto(safe_url, wait_until=wait_until, timeout=timeout_ms)
            try:
                validator.validate(page.url)
            except URLPolicyError as exc:
                raise RenderError(str(exc)) from exc
            html = page.content()
            final_url = page.url

            saved_screenshot = None
            if screenshot_path:
                screenshot_file = Path(screenshot_path)
                screenshot_file.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_file), full_page=True)
                saved_screenshot = str(screenshot_file)

            saved_html = None
            if html_snapshot_path:
                html_file = Path(html_snapshot_path)
                html_file.parent.mkdir(parents=True, exist_ok=True)
                html_file.write_text(html, encoding="utf-8")
                saved_html = str(html_file)

            return RenderedPage(
                url=url,
                html=html,
                final_url=final_url,
                screenshot_path=saved_screenshot,
                html_snapshot_path=saved_html,
            )
        except Exception as exc:
            raise RenderError(f"Failed to render {url}: {exc}") from exc
        finally:
            context.close()
            browser.close()


def _route_request(route: Any, request: Any, validator: URLValidator) -> None:
    scheme = urlsplit(request.url).scheme.lower()
    if scheme in {"data", "blob", "about"}:
        route.continue_()
        return
    try:
        validator.validate(request.url)
    except URLPolicyError:
        route.abort("blockedbyclient")
        return
    route.continue_()
