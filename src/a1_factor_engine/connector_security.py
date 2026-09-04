"""Fail-closed policy helpers for deployment-provided HTTP connector transports."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import AsyncIterable, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

CONNECTOR_URL_REJECTED = "CONNECTOR_URL_REJECTED"
CONNECTOR_REDIRECT_REJECTED = "CONNECTOR_REDIRECT_REJECTED"
CONNECTOR_RESPONSE_TOO_LARGE = "CONNECTOR_RESPONSE_TOO_LARGE"
CONNECTOR_RESPONSE_TOO_COMPLEX = "CONNECTOR_RESPONSE_TOO_COMPLEX"
CONNECTOR_TIMEOUT = "CONNECTOR_TIMEOUT"
CONNECTOR_FETCH_FAILED = "CONNECTOR_FETCH_FAILED"
CONNECTOR_PEER_UNVERIFIED = "CONNECTOR_PEER_UNVERIFIED"


class ConnectorSecurityError(RuntimeError):
    """A stable, non-sensitive connector policy failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ConnectorLimits:
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 15.0
    max_response_bytes: int = 2_000_000
    max_json_depth: int = 24
    max_records: int = 250
    max_documents: int = 25
    max_redirects: int = 3


@dataclass(frozen=True, slots=True)
class ValidatedRoute:
    """A hostname route bound to the public addresses validated for one hop."""

    url: str
    scheme: str
    hostname: str
    port: int
    resolved_ips: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ConnectorTransportContext:
    """Connection contract passed to a deployment-owned bound transport."""

    route: ValidatedRoute
    limits: ConnectorLimits

    @property
    def connect_timeout_seconds(self) -> float:
        return self.limits.connect_timeout_seconds

    @property
    def read_timeout_seconds(self) -> float:
        return self.limits.read_timeout_seconds


@dataclass(frozen=True, slots=True)
class StructuredFetchResponse:
    """Auditable response envelope returned by a deployment transport.

    A transport must not follow redirects itself. It returns one ``redirect_to``
    hop so CFR can validate it and regenerate per-origin request headers.
    """

    body: bytes | Mapping[str, Any] | Sequence[Any] | AsyncIterable[bytes]
    final_url: str
    redirect_chain: tuple[str, ...] = ()
    redirect_to: str | None = None
    peer_ip: str | None = None


def bound_transport(value: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a deployment transport that binds connections to ``context.route``."""

    # Callable transports do not share a concrete protocol implementation.
    setattr(value, "cfr_binds_validated_route", True)  # noqa: B010
    return value


def is_bound_transport(value: Any) -> bool:
    return bool(getattr(value, "cfr_binds_validated_route", False))


def _origin(parts: SplitResult) -> tuple[str, str, int]:
    default = 443 if parts.scheme.casefold() == "https" else 80
    return parts.scheme.casefold(), (parts.hostname or "").casefold(), parts.port or default


def _default_resolver(host: str, port: int) -> Iterable[str]:
    return {str(item[4][0]) for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}


def _public_ip(value: str) -> bool:
    address = ipaddress.ip_address(value.split("%", 1)[0])
    return bool(address.is_global)


@dataclass(frozen=True, slots=True)
class OutboundRequestPolicy:
    base_url: str
    allowed_hosts: tuple[str, ...] = ()
    allow_cross_origin_redirects: bool = False
    resolver: Callable[[str, int], Iterable[str]] = field(default=_default_resolver, repr=False)
    limits: ConnectorLimits = field(default_factory=ConnectorLimits)

    @property
    def base_origin(self) -> tuple[str, str, int]:
        return _origin(self.validate_url(self.base_url, resolve_dns=False))

    def validate_url(self, url: str, *, resolve_dns: bool = True) -> SplitResult:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError as exc:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector URL is not permitted") from exc
        if parts.scheme.casefold() != "https" or not parts.hostname or parts.username or parts.password:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector URL is not permitted")
        host = parts.hostname.casefold().rstrip(".")
        base = urlsplit(self.base_url)
        allowed = {base.hostname.casefold().rstrip(".") if base.hostname else ""}
        allowed.update(item.casefold().rstrip(".") for item in self.allowed_hosts)
        if host not in allowed:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector origin is not permitted")
        effective_port = port or 443
        base_port = base.port or 443
        if effective_port != base_port:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector origin is not permitted")
        try:
            literal = ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            literal = None
        if literal is not None and not literal.is_global:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector address is not permitted")
        if resolve_dns:
            try:
                addresses = tuple(self.resolver(host, effective_port))
            except (OSError, ValueError) as exc:
                raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector DNS validation failed") from exc
            if not addresses or any(not _public_ip(item) for item in addresses):
                raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector address is not permitted")
        return parts

    def resolve_route(self, url: str) -> ValidatedRoute:
        parts = self.validate_url(url, resolve_dns=False)
        host = (parts.hostname or "").casefold().rstrip(".")
        port = parts.port or 443
        try:
            addresses = tuple(sorted(set(self.resolver(host, port))))
        except (OSError, ValueError) as exc:
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector DNS validation failed") from exc
        if not addresses or any(not _public_ip(item) for item in addresses):
            raise ConnectorSecurityError(CONNECTOR_URL_REJECTED, "connector address is not permitted")
        return ValidatedRoute(url, parts.scheme.casefold(), host, port, addresses)

    def request_headers(self, route: ValidatedRoute, authorization: str) -> Mapping[str, str]:
        headers = {"Accept": "application/json"}
        if (route.scheme, route.hostname, route.port) == self.base_origin:
            headers["Authorization"] = authorization
        return headers

    def validate_response_route(self, route: ValidatedRoute, response: StructuredFetchResponse) -> None:
        requested_url = route.url
        requested = self.validate_url(requested_url, resolve_dns=False)
        if response.redirect_chain:
            raise ConnectorSecurityError(
                CONNECTOR_REDIRECT_REJECTED,
                "connector transport must not follow redirects automatically",
            )
        if not response.redirect_to and urljoin(requested_url, response.final_url) != requested_url:
            raise ConnectorSecurityError(
                CONNECTOR_REDIRECT_REJECTED,
                "connector transport changed URL without an explicit redirect",
            )
        if not response.peer_ip or response.peer_ip not in route.resolved_ips or not _public_ip(response.peer_ip):
            raise ConnectorSecurityError(
                CONNECTOR_PEER_UNVERIFIED,
                "connector peer address was not bound to the validated route",
            )
        previous = requested_url
        hops = tuple(item for item in (response.redirect_to, response.final_url) if item)
        for target in hops:
            resolved = urljoin(previous, target)
            parts = self.validate_url(resolved, resolve_dns=False)
            if _origin(parts) != _origin(requested) and not self.allow_cross_origin_redirects:
                raise ConnectorSecurityError(
                    CONNECTOR_REDIRECT_REJECTED, "cross-origin connector redirect is not permitted"
                )
            previous = resolved


def redact_sensitive_text(value: str) -> str:
    """Remove credentials, URL queries and internal addresses from diagnostics."""

    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)([^\s,;]+(?:\s+[^\s,;]+)?)", r"\1[REDACTED]", value)
    value = re.sub(r"https?://[^\s]+", lambda match: _safe_url(match.group(0)), value)
    value = re.sub(
        r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])",
        lambda match: _redact_address(match.group(0)),
        value,
    )
    value = re.sub(
        r"(?i)(?<![\w:])(?:\[[0-9a-f:]+(?:%[^\]]+)?\]|[0-9a-f]*:[0-9a-f:]+)(?![\w:])",
        lambda match: _redact_address(match.group(0)),
        value,
    )
    return value


def _redact_address(value: str) -> str:
    candidate = value.strip("[]").split("%", 1)[0]
    try:
        return value if ipaddress.ip_address(candidate).is_global else "[REDACTED_ADDRESS]"
    except ValueError:
        return value


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value.rstrip(".,;"))
        host = parts.hostname or "[REDACTED_HOST]"
        if not _public_host_for_display(host):
            host = "[REDACTED_HOST]"
        port = f":{parts.port}" if parts.port else ""
        return urlunsplit((parts.scheme, f"{host}{port}", parts.path, "", ""))
    except (ValueError, OSError):
        return "[REDACTED_URL]"


def _public_host_for_display(host: str) -> bool:
    try:
        return _public_ip(host)
    except ValueError:
        return host.casefold() not in {"localhost", "localhost.localdomain"}


def validate_json_complexity(value: Any, limits: ConnectorLimits) -> None:
    records = 0

    def visit(item: Any, depth: int) -> None:
        nonlocal records
        if depth > limits.max_json_depth:
            raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_COMPLEX, "connector JSON is too deep")
        if isinstance(item, Mapping):
            records += 1
            if records > limits.max_records:
                raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_COMPLEX, "connector JSON has too many records")
            for child in item.values():
                visit(child, depth + 1)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            if len(item) > limits.max_documents:
                raise ConnectorSecurityError(
                    CONNECTOR_RESPONSE_TOO_COMPLEX, "connector response has too many documents"
                )
            for child in item:
                visit(child, depth + 1)

    visit(value, 0)


async def consume_structured_response(
    response: StructuredFetchResponse, limits: ConnectorLimits, *, preserve_bytes: bool = False
) -> Any:
    body = response.body
    if isinstance(body, AsyncIterable):
        collected = bytearray()
        async for chunk in body:
            collected.extend(chunk)
            if len(collected) > limits.max_response_bytes:
                raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_LARGE, "connector response is too large")
        body = bytes(collected)
    if isinstance(body, bytes):
        if len(body) > limits.max_response_bytes:
            raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_LARGE, "connector response is too large")
        try:
            value = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_COMPLEX, "connector response is not valid JSON") from exc
    else:
        try:
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise ConnectorSecurityError(
                CONNECTOR_RESPONSE_TOO_COMPLEX, "connector response is not valid JSON"
            ) from exc
        if len(encoded) > limits.max_response_bytes:
            raise ConnectorSecurityError(CONNECTOR_RESPONSE_TOO_LARGE, "connector response is too large")
        value = body
    validate_json_complexity(value, limits)
    return body if preserve_bytes and isinstance(body, bytes) else value


async def run_with_total_timeout(value: Awaitable[Any], limits: ConnectorLimits) -> Any:
    try:
        return await asyncio.wait_for(value, timeout=limits.total_timeout_seconds)
    except TimeoutError as exc:
        raise ConnectorSecurityError(CONNECTOR_TIMEOUT, "connector request timed out") from exc
