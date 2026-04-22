"""Canonical outbound HTTP helpers for updater and release runtime flows.

Keep updater-owned HTTP call sites on these helpers so timeout, redirect,
status, and error mapping stay consistent instead of re-creating low-level
client plumbing at each boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx
import msgspec

from vibesensor.shared.types.json_types import JsonValue

__all__ = [
    "build_request",
    "build_get_request",
    "read_json_response",
    "read_typed_json_response",
    "read_text_response",
    "stream_http_response",
]


def build_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    context: str = "operation",
    require_https: bool = False,
) -> httpx.Request:
    """Build a request after applying the shared runtime safety checks."""

    if require_https and not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS URL for {context}: {url}")
    return httpx.Request(method.upper(), url, headers=dict(headers or {}), content=content)


def build_get_request(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    context: str = "operation",
    require_https: bool = False,
) -> httpx.Request:
    """Build a GET request after applying the shared runtime safety checks."""

    return build_request(
        "GET",
        url,
        headers=headers,
        context=context,
        require_https=require_https,
    )


def _http_error_as_oserror(exc: httpx.HTTPError, *, context: str, url: str) -> OSError:
    if isinstance(exc, httpx.HTTPStatusError):
        diagnostic = _status_error_diagnostic(exc.response)
        return OSError(
            f"{context} request failed with HTTP {exc.response.status_code}: {url}{diagnostic}"
        )
    return OSError(f"{context} request failed for {url}: {exc}")


def _status_error_diagnostic(response: httpx.Response) -> str:
    parts = []
    body = _response_body_excerpt(response)
    if body:
        parts.append(f"body={body!r}")
    headers = _diagnostic_headers(response.headers)
    if headers:
        parts.append(f"headers={headers}")
    if not parts:
        return ""
    return f" ({'; '.join(parts)})"


def _response_body_excerpt(response: httpx.Response, *, limit: int = 500) -> str:
    try:
        text = response.text
    except httpx.ResponseNotRead:
        return ""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _diagnostic_headers(headers: httpx.Headers) -> dict[str, str]:
    names = (
        "x-github-request-id",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
        "x-ratelimit-used",
        "x-ratelimit-reset",
        "retry-after",
    )
    return {name: value for name in names if (value := headers.get(name))}


def _client(
    *,
    timeout_s: float,
    transport: httpx.BaseTransport | None,
) -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=timeout_s,
        transport=transport,
    )


def read_json_response(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> JsonValue:
    """Send a request and decode the response body as JSON."""

    request = build_request(
        method,
        url,
        headers=headers,
        content=content,
        context=context,
        require_https=require_https,
    )
    try:
        with _client(timeout_s=timeout_s, transport=transport) as client:
            response = client.send(request)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _http_error_as_oserror(exc, context=context, url=url) from exc

    try:
        payload: JsonValue = json.loads(response.content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{context} returned invalid JSON: {exc}") from exc
    return payload


def read_typed_json_response(
    url: str,
    *,
    response_type: Any,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> Any:
    """Send a request and decode the response body as typed JSON via msgspec."""

    request = build_request(
        method,
        url,
        headers=headers,
        content=content,
        context=context,
        require_https=require_https,
    )
    try:
        with _client(timeout_s=timeout_s, transport=transport) as client:
            response = client.send(request)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise _http_error_as_oserror(exc, context=context, url=url) from exc

    try:
        payload = msgspec.json.decode(response.content, type=response_type)
    except (msgspec.DecodeError, msgspec.ValidationError) as exc:
        raise ValueError(f"{context} returned invalid JSON: {exc}") from exc
    return payload


def read_text_response(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> tuple[int, str, str]:
    """Send a request and return status, content type, and decoded body text."""

    request = build_request(
        method,
        url,
        headers=headers,
        content=content,
        context=context,
        require_https=require_https,
    )
    try:
        with _client(timeout_s=timeout_s, transport=transport) as client:
            response = client.send(request)
    except httpx.HTTPError as exc:
        raise _http_error_as_oserror(exc, context=context, url=url) from exc
    return response.status_code, response.headers.get("Content-Type", ""), response.text


@contextmanager
def stream_http_response(
    url: str,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[httpx.Response]:
    """Stream a successful response body for updater-owned callers."""

    request = build_request(
        method,
        url,
        headers=headers,
        content=content,
        context=context,
        require_https=require_https,
    )
    try:
        with _client(timeout_s=timeout_s, transport=transport) as client:
            with client.stream(
                request.method,
                request.url,
                headers=request.headers,
                content=request.content,
            ) as response:
                response.raise_for_status()
                yield response
    except httpx.HTTPError as exc:
        raise _http_error_as_oserror(exc, context=context, url=url) from exc
