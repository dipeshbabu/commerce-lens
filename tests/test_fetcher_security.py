from __future__ import annotations

import asyncio
import socket

import httpx
import pytest

from commercelens.core.fetcher import FetchError, fetch_html, fetch_html_async
from commercelens.core.url_policy import URLPolicy


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


def html_response(request: httpx.Request, content: bytes = b"<html>ok</html>") -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        content=content,
        request=request,
    )


def test_fetch_html_reads_a_valid_public_html_response() -> None:
    transport = httpx.MockTransport(html_response)

    result = fetch_html(
        "https://store.example/product",
        resolver=public_resolver,
        transport=transport,
    )

    assert result == "<html>ok</html>"


def test_fetch_html_async_uses_the_same_policy() -> None:
    transport = httpx.MockTransport(html_response)

    result = asyncio.run(
        fetch_html_async(
            "https://store.example/product",
            resolver=public_resolver,
            transport=transport,
        )
    )

    assert result == "<html>ok</html>"


def test_fetch_html_rejects_a_redirect_to_private_address_space() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/admin"},
            request=request,
        )

    with pytest.raises(FetchError, match="non-public address space"):
        fetch_html(
            "https://store.example/product",
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        )

    assert requests == ["https://store.example/product"]


def test_fetch_html_limits_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "/next"},
            request=request,
        )

    with pytest.raises(FetchError, match="Too many redirects"):
        fetch_html(
            "https://store.example/product",
            policy=URLPolicy(max_redirects=1),
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        )


def test_fetch_html_requires_an_html_content_type() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            json={"name": "not html"},
            request=request,
        )

    with pytest.raises(FetchError, match="Expected an HTML response"):
        fetch_html(
            "https://store.example/product",
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        )


def test_fetch_html_rejects_declared_oversized_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html", "Content-Length": "100"},
            content=b"short",
            request=request,
        )

    with pytest.raises(FetchError, match="maximum size"):
        fetch_html(
            "https://store.example/product",
            policy=URLPolicy(max_response_bytes=10),
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        )


def test_fetch_html_limits_decoded_response_bytes() -> None:
    transport = httpx.MockTransport(lambda request: html_response(request, b"x" * 11))

    with pytest.raises(FetchError, match="maximum size"):
        fetch_html(
            "https://store.example/product",
            policy=URLPolicy(max_response_bytes=10),
            resolver=public_resolver,
            transport=transport,
        )


def test_fetch_errors_do_not_expose_query_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    with pytest.raises(FetchError) as exc:
        fetch_html(
            "https://store.example/product?token=super-secret",
            resolver=public_resolver,
            transport=httpx.MockTransport(handler),
        )

    assert "super-secret" not in str(exc.value)
