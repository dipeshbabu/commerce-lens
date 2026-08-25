from __future__ import annotations

import asyncio
import os
import socket
from typing import Any
from urllib.parse import urljoin

import httpx

from commercelens.core.url_policy import (
    Resolver,
    URLPolicy,
    URLPolicyError,
    URLValidator,
    redact_url,
)
from commercelens.version import __version__

DEFAULT_USER_AGENT = f"CommerceLens/{__version__} (+https://github.com/dipeshbabu/commerce-lens)"
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchError(RuntimeError):
    """Raised when CommerceLens cannot fetch a URL."""


async def fetch_html_async(
    url: str,
    timeout: float = 20.0,
    *,
    policy: URLPolicy | None = None,
    resolver: Resolver = socket.getaddrinfo,
    transport: Any | None = None,
) -> str:
    timeout = _configured_timeout(timeout)
    headers = {"User-Agent": _configured_user_agent()}
    validator = URLValidator(policy=policy, resolver=resolver)
    current_url = await asyncio.to_thread(_validate_url, url, validator)

    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
        transport=transport,
    ) as client:
        for redirect_count in range(validator.policy.max_redirects + 1):
            try:
                async with client.stream("GET", current_url) as response:
                    redirect = _redirect_target(response, current_url)
                    if redirect is not None:
                        if redirect_count >= validator.policy.max_redirects:
                            raise FetchError(
                                f"Too many redirects while fetching {redact_url(url)}."
                            )
                        current_url = await asyncio.to_thread(_validate_url, redirect, validator)
                        continue
                    _ensure_success(response, current_url)
                    _ensure_html_response(response, validator.policy)
                    body = await _read_limited_async(response, validator.policy)
                    return _decode_body(response, body)
            except httpx.TimeoutException as exc:
                raise FetchError(
                    f"Timed out fetching {redact_url(current_url)} after {timeout:g}s."
                ) from exc
            except httpx.RequestError as exc:
                raise FetchError(
                    f"Request failed while fetching {redact_url(current_url)}: "
                    f"{exc.__class__.__name__}."
                ) from exc

    raise FetchError(f"Could not fetch {redact_url(url)}.")


def fetch_html(
    url: str,
    timeout: float = 20.0,
    *,
    policy: URLPolicy | None = None,
    resolver: Resolver = socket.getaddrinfo,
    transport: Any | None = None,
) -> str:
    timeout = _configured_timeout(timeout)
    headers = {"User-Agent": _configured_user_agent()}
    validator = URLValidator(policy=policy, resolver=resolver)
    current_url = _validate_url(url, validator)

    with httpx.Client(
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
        transport=transport,
    ) as client:
        for redirect_count in range(validator.policy.max_redirects + 1):
            try:
                with client.stream("GET", current_url) as response:
                    redirect = _redirect_target(response, current_url)
                    if redirect is not None:
                        if redirect_count >= validator.policy.max_redirects:
                            raise FetchError(
                                f"Too many redirects while fetching {redact_url(url)}."
                            )
                        current_url = _validate_url(redirect, validator)
                        continue
                    _ensure_success(response, current_url)
                    _ensure_html_response(response, validator.policy)
                    body = _read_limited(response, validator.policy)
                    return _decode_body(response, body)
            except httpx.TimeoutException as exc:
                raise FetchError(
                    f"Timed out fetching {redact_url(current_url)} after {timeout:g}s."
                ) from exc
            except httpx.RequestError as exc:
                raise FetchError(
                    f"Request failed while fetching {redact_url(current_url)}: "
                    f"{exc.__class__.__name__}."
                ) from exc

    raise FetchError(f"Could not fetch {redact_url(url)}.")


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


def _validate_url(url: str, validator: URLValidator) -> str:
    try:
        return validator.validate(url)
    except URLPolicyError as exc:
        raise FetchError(str(exc)) from exc


def _redirect_target(response: httpx.Response, current_url: str) -> str | None:
    if response.status_code not in _REDIRECT_STATUSES:
        return None
    location = response.headers.get("location")
    if not location:
        raise FetchError(
            f"Redirect from {redact_url(current_url)} did not include a Location header."
        )
    return urljoin(current_url, location)


def _ensure_success(response: httpx.Response, current_url: str) -> None:
    if response.status_code >= 400:
        raise FetchError(f"Failed to fetch {redact_url(current_url)}: HTTP {response.status_code}.")


def _ensure_html_response(response: httpx.Response, policy: URLPolicy) -> None:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in policy.allowed_content_types:
        display = content_type or "missing"
        raise FetchError(f"Expected an HTML response but received content type {display!r}.")

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = 0
        if declared_size > policy.max_response_bytes:
            raise FetchError(
                f"Response exceeds the maximum size of {policy.max_response_bytes} bytes."
            )


def _read_limited(response: httpx.Response, policy: URLPolicy) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > policy.max_response_bytes:
            raise FetchError(
                f"Response exceeds the maximum size of {policy.max_response_bytes} bytes."
            )
    return bytes(body)


async def _read_limited_async(response: httpx.Response, policy: URLPolicy) -> bytes:
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > policy.max_response_bytes:
            raise FetchError(
                f"Response exceeds the maximum size of {policy.max_response_bytes} bytes."
            )
    return bytes(body)


def _decode_body(response: httpx.Response, body: bytes) -> str:
    encoding = response.encoding or "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")
