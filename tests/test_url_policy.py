from __future__ import annotations

import socket

import pytest

from commercelens.core.url_policy import URLPolicy, URLPolicyError, URLValidator, redact_url


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


def mixed_resolver(host: str, port: int, **kwargs):
    return [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("93.184.216.34", port),
        ),
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", port),
        ),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/catalog",
        "http://localhost/admin",
        "http://shop.localhost/admin",
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
        "https://user:password@example.com/product",
    ],
)
def test_validator_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(URLPolicyError):
        URLValidator(resolver=public_resolver).validate(url)


def test_validator_accepts_a_public_destination() -> None:
    result = URLValidator(resolver=public_resolver).validate(
        "HTTPS://Store.Example:443/products/widget?color=blue#reviews"
    )

    assert result == "https://store.example/products/widget?color=blue"


def test_validator_rejects_a_hostname_with_any_private_answer() -> None:
    with pytest.raises(URLPolicyError, match="non-public address space"):
        URLValidator(resolver=mixed_resolver).validate("https://store.example/product")


def test_explicit_private_host_allowlist_is_exact() -> None:
    policy = URLPolicy(allowed_private_hosts=frozenset({"catalog.internal.example"}))
    validator = URLValidator(policy=policy, resolver=mixed_resolver)

    assert (
        validator.validate("https://catalog.internal.example/product")
        == "https://catalog.internal.example/product"
    )
    with pytest.raises(URLPolicyError):
        validator.validate("https://other.catalog.internal.example/product")


def test_private_host_allowlist_cannot_enable_metadata_address() -> None:
    policy = URLPolicy(allowed_private_hosts=frozenset({"169.254.169.254"}))

    with pytest.raises(URLPolicyError, match="always blocked"):
        URLValidator(policy=policy).validate("http://169.254.169.254/latest/meta-data")


def test_validator_caches_approved_host_resolution() -> None:
    calls = 0

    def resolver(host: str, port: int, **kwargs):
        nonlocal calls
        calls += 1
        return public_resolver(host, port, **kwargs)

    validator = URLValidator(resolver=resolver)
    validator.validate("https://store.example/one")
    validator.validate("https://store.example/two")

    assert calls == 1


def test_redact_url_removes_credentials_query_and_fragment() -> None:
    assert (
        redact_url("https://user:secret@store.example/product?token=private#details")
        == "https://store.example/product"
    )
