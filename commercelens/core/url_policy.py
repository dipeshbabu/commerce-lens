from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

Resolver = Callable[..., Iterable[tuple[Any, ...]]]

DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_URL_LENGTH = 4096

_BLOCKED_HOSTNAMES = frozenset(
    {
        "instance-data",
        "metadata",
        "metadata.google.internal",
    }
)
_BLOCKED_IPS = frozenset(
    {
        ipaddress.ip_address("100.100.100.200"),
        ipaddress.ip_address("169.254.169.254"),
    }
)


class URLPolicyError(ValueError):
    """Raised when an outbound URL violates the configured network policy."""


@dataclass(frozen=True, slots=True)
class URLPolicy:
    allowed_private_hosts: frozenset[str] = field(default_factory=frozenset)
    max_redirects: int = DEFAULT_MAX_REDIRECTS
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    max_url_length: int = DEFAULT_MAX_URL_LENGTH
    allowed_content_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"text/html", "application/xhtml+xml"})
    )

    @classmethod
    def from_env(cls) -> URLPolicy:
        return cls(
            allowed_private_hosts=frozenset(
                _normalize_hostname(host)
                for host in os.getenv("COMMERCELENS_ALLOWED_PRIVATE_HOSTS", "").split(",")
                if host.strip()
            ),
            max_redirects=_read_positive_int(
                "COMMERCELENS_MAX_REDIRECTS",
                DEFAULT_MAX_REDIRECTS,
                allow_zero=True,
            ),
            max_response_bytes=_read_positive_int(
                "COMMERCELENS_MAX_RESPONSE_BYTES",
                DEFAULT_MAX_RESPONSE_BYTES,
            ),
            max_url_length=_read_positive_int(
                "COMMERCELENS_MAX_URL_LENGTH",
                DEFAULT_MAX_URL_LENGTH,
            ),
        )


class URLValidator:
    """Validate outbound destinations and cache approved DNS results per request."""

    def __init__(
        self,
        policy: URLPolicy | None = None,
        resolver: Resolver = socket.getaddrinfo,
    ) -> None:
        self.policy = policy or URLPolicy.from_env()
        self.resolver = resolver
        self._approved: set[tuple[str, int]] = set()

    def validate(self, url: str) -> str:
        if not isinstance(url, str) or not url.strip():
            raise URLPolicyError("URL must be a non-empty string.")
        if len(url) > self.policy.max_url_length:
            raise URLPolicyError(
                f"URL exceeds the maximum length of {self.policy.max_url_length} characters."
            )

        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"}:
            raise URLPolicyError("Only http and https URLs are allowed.")
        if parsed.username is not None or parsed.password is not None:
            raise URLPolicyError("URLs with embedded credentials are not allowed.")
        if not parsed.hostname:
            raise URLPolicyError("URL must include a hostname.")

        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError as exc:
            raise URLPolicyError("URL contains an invalid port.") from exc

        hostname = _normalize_hostname(parsed.hostname)
        if not hostname:
            raise URLPolicyError("URL must include a valid hostname.")
        if (
            hostname in _BLOCKED_HOSTNAMES
            or hostname == "localhost"
            or hostname.endswith(".localhost")
        ):
            raise URLPolicyError(f"Outbound requests to {hostname!r} are blocked.")

        key = (hostname, port)
        if key not in self._approved:
            self._validate_destination(hostname, port)
            self._approved.add(key)

        netloc = _normalized_netloc(hostname, port, scheme)
        return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))

    def _validate_destination(self, hostname: str, port: int) -> None:
        trusted = hostname in self.policy.allowed_private_hosts
        addresses = _resolve_addresses(hostname, port, self.resolver)
        if not addresses:
            raise URLPolicyError(f"Hostname {hostname!r} did not resolve to an address.")
        blocked_metadata = sorted(str(address) for address in addresses if address in _BLOCKED_IPS)
        if blocked_metadata:
            joined = ", ".join(blocked_metadata)
            raise URLPolicyError(f"Cloud metadata destinations are always blocked: {joined}.")
        if trusted:
            return

        unsafe = sorted(str(address) for address in addresses if not _is_public_address(address))
        if unsafe:
            joined = ", ".join(unsafe)
            raise URLPolicyError(
                f"Outbound requests to non-public address space are blocked: {joined}."
            )


def redact_url(url: str) -> str:
    """Return a URL safe for errors and logs by removing credentials and query data."""

    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        port = parsed.port
        scheme = parsed.scheme.lower()
        netloc = _normalized_netloc(hostname, port, scheme) if hostname else ""
        return urlunsplit((scheme, netloc, parsed.path or "/", "", ""))
    except ValueError:
        return "<invalid-url>"


def _normalize_hostname(hostname: str) -> str:
    value = hostname.strip().rstrip(".").lower()
    if not value:
        return ""
    try:
        return value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise URLPolicyError("URL hostname is not valid IDNA.") from exc


def _normalized_netloc(hostname: str, port: int | None, scheme: str) -> str:
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    if port is None or port == default_port:
        return display_host
    return f"{display_host}:{port}"


def _resolve_addresses(
    hostname: str, port: int, resolver: Resolver
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return {ipaddress.ip_address(hostname)}
    except ValueError:
        pass

    try:
        records = resolver(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise URLPolicyError(f"Could not resolve hostname {hostname!r}.") from exc

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for record in records:
        if len(record) < 5 or not record[4]:
            continue
        raw_address = record[4][0]
        try:
            addresses.add(ipaddress.ip_address(raw_address))
        except ValueError:
            continue
    return addresses


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_global and address not in _BLOCKED_IPS


def _read_positive_int(name: str, default: int, *, allow_zero: bool = False) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise URLPolicyError(f"{name} must be an integer.") from exc
    minimum = 0 if allow_zero else 1
    if value < minimum:
        qualifier = "zero or greater" if allow_zero else "greater than zero"
        raise URLPolicyError(f"{name} must be {qualifier}.")
    return value
