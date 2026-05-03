from __future__ import annotations

import os

import httpx
from httpx import TimeoutException

DEFAULT_USER_AGENT = (
    "CommerceLens/0.9 (+https://github.com/dipeshbabu/commerce-lens)"
)


class FetchError(RuntimeError):
    """Raised when CommerceLens cannot fetch a URL."""


async def fetch_html_async(url: str, timeout: float = 20.0) -> str:
    timeout = _configured_timeout(timeout)
    headers = {"User-Agent": _configured_user_agent()}
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        try:
            response = await client.get(url)
        except TimeoutException as exc:
            raise FetchError(f"Timed out fetching {url} after {timeout:g}s") from exc
        if response.status_code >= 400:
            raise FetchError(f"Failed to fetch {url}: HTTP {response.status_code}")
        return response.text


def fetch_html(url: str, timeout: float = 20.0) -> str:
    timeout = _configured_timeout(timeout)
    headers = {"User-Agent": _configured_user_agent()}
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        try:
            response = client.get(url)
        except TimeoutException as exc:
            raise FetchError(f"Timed out fetching {url} after {timeout:g}s") from exc
        if response.status_code >= 400:
            raise FetchError(f"Failed to fetch {url}: HTTP {response.status_code}")
        return response.text


def _configured_user_agent() -> str:
    return os.getenv("COMMERCELENS_USER_AGENT", DEFAULT_USER_AGENT)


def _configured_timeout(default: float) -> float:
    raw = os.getenv("COMMERCELENS_DEFAULT_TIMEOUT_SECONDS")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise FetchError("COMMERCELENS_DEFAULT_TIMEOUT_SECONDS must be a number.") from exc
