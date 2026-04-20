"""Canonical outbound HTTP helpers for updater and release runtime flows.

Keep updater-owned HTTP call sites on these helpers so timeout, redirect,
status, and error mapping stay consistent instead of re-creating low-level
client plumbing at each boundary.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import httpx

from vibesensor.shared.types.json_types import JsonValue

__all__ = [
    "build_get_request",
    "read_json_response",
    "read_text_response",
    "stream_http_response",
]


def build_get_request(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    context: str = "operation",
    require_https: bool = False,
) -> httpx.Request:
    """Build a GET request after applying the shared runtime safety checks."""

    if require_https and not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS URL for {context}: {url}")
    return httpx.Request("GET", url, headers=dict(headers or {}))


def _http_error_as_oserror(exc: httpx.HTTPError, *, context: str, url: str) -> OSError:
    if isinstance(exc, httpx.HTTPStatusError):
        return OSError(f"{context} request failed with HTTP {exc.response.status_code}: {url}")
    return OSError(f"{context} request failed for {url}: {exc}")


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
    headers: Mapping[str, str] | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> JsonValue:
    """GET *url* and decode the body as JSON."""

    request = build_get_request(
        url,
        headers=headers,
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


def read_text_response(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> tuple[int, str, str]:
    """GET *url* and return status, content type, and decoded body text."""

    request = build_get_request(
        url,
        headers=headers,
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
    headers: Mapping[str, str] | None = None,
    timeout_s: float,
    context: str,
    require_https: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[httpx.Response]:
    """Stream a successful GET response body for updater-owned callers."""

    request = build_get_request(
        url,
        headers=headers,
        context=context,
        require_https=require_https,
    )
    try:
        with _client(timeout_s=timeout_s, transport=transport) as client:
            with client.stream("GET", request.url, headers=request.headers) as response:
                response.raise_for_status()
                yield response
    except httpx.HTTPError as exc:
        raise _http_error_as_oserror(exc, context=context, url=url) from exc
