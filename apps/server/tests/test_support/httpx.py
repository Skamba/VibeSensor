from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from pytest_httpx import HTTPXMock


def add_json_response(
    httpx_mock: HTTPXMock,
    *,
    url: str,
    payload: Any,
    status_code: int = 200,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
) -> None:
    response_headers = {"Content-Type": "application/json"}
    if headers is not None:
        response_headers.update(headers)
    httpx_mock.add_response(
        method=method,
        url=url,
        json=payload,
        status_code=status_code,
        headers=response_headers,
    )


def add_text_response(
    httpx_mock: HTTPXMock,
    *,
    url: str,
    text: str,
    status_code: int = 200,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
) -> None:
    response_headers = {"Content-Type": "text/plain; charset=utf-8"}
    if headers is not None:
        response_headers.update(headers)
    httpx_mock.add_response(
        method=method,
        url=url,
        text=text,
        status_code=status_code,
        headers=response_headers,
    )


def add_bytes_response(
    httpx_mock: HTTPXMock,
    *,
    url: str,
    content: bytes,
    status_code: int = 200,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
) -> None:
    response_headers = {"Content-Type": "application/octet-stream"}
    if headers is not None:
        response_headers.update(headers)
    httpx_mock.add_response(
        method=method,
        url=url,
        content=content,
        status_code=status_code,
        headers=response_headers,
    )


def add_httpx_exception(
    httpx_mock: HTTPXMock,
    *,
    url: str,
    exception: httpx.HTTPError,
    method: str = "GET",
) -> None:
    httpx_mock.add_exception(exception, method=method, url=url)
