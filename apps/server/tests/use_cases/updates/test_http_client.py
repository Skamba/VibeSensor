from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock
from test_support.httpx import (
    add_bytes_response,
    add_httpx_exception,
    add_json_response,
    add_text_response,
)

from vibesensor.use_cases.updates.asset_download import download_release_asset
from vibesensor.use_cases.updates.http_client import (
    build_get_request,
    build_request,
    read_text_response,
    stream_http_response,
)
from vibesensor.use_cases.updates.releases.github_api import GitHubApiClient


def test_build_get_request_rejects_non_https_when_required() -> None:
    with pytest.raises(ValueError, match="non-HTTPS"):
        build_get_request(
            "http://example.com/releases",
            context="release",
            require_https=True,
        )


def test_build_request_keeps_method_and_body_for_json_puts() -> None:
    request = build_request(
        "put",
        "http://127.0.0.1:8000/api/settings/speed-source",
        headers={"Content-Type": "application/json"},
        content=b'{"speed_source":"manual"}',
        context="simulator speed override",
    )

    assert request.method == "PUT"
    assert str(request.url) == "http://127.0.0.1:8000/api/settings/speed-source"
    assert request.headers["Content-Type"] == "application/json"
    assert request.content == b'{"speed_source":"manual"}'


def test_github_api_client_get_json_decodes_payload(httpx_mock: HTTPXMock) -> None:
    url = "https://api.github.com/repos/owner/repo/releases"
    add_json_response(httpx_mock, url=url, payload={"ok": True})
    client = GitHubApiClient()

    assert client.get_json(url) == {"ok": True}
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].headers["Accept"] == "application/vnd.github+json"


def test_github_api_client_get_json_maps_non_200_to_oserror(httpx_mock: HTTPXMock) -> None:
    url = "https://api.github.com/repos/owner/repo/releases"
    add_text_response(httpx_mock, url=url, text="busy", status_code=503)
    client = GitHubApiClient()

    with pytest.raises(OSError, match="HTTP 503"):
        client.get_json(url)


def test_github_api_client_get_json_rejects_invalid_json(httpx_mock: HTTPXMock) -> None:
    url = "https://api.github.com/repos/owner/repo/releases"
    add_text_response(httpx_mock, url=url, text="{not-json")
    client = GitHubApiClient()

    with pytest.raises(ValueError, match="invalid JSON"):
        client.get_json(url)


def test_read_text_response_returns_status_and_body_for_local_smoke_checks(
    httpx_mock: HTTPXMock,
) -> None:
    url = "http://127.0.0.1:8000/api/health"
    add_text_response(httpx_mock, url=url, text="booting", status_code=503)
    status, content_type, body = read_text_response(
        url,
        timeout_s=3.0,
        context="release smoke",
    )

    assert status == 503
    assert content_type == "text/plain; charset=utf-8"
    assert body == "booting"


def test_read_text_response_supports_put_with_request_body(httpx_mock: HTTPXMock) -> None:
    url = "http://127.0.0.1:8000/api/settings/speed-source"
    add_text_response(httpx_mock, url=url, text="ok", method="PUT")
    status, _content_type, body = read_text_response(
        url,
        method="PUT",
        headers={"Content-Type": "application/json"},
        content=b'{"speed_source":"manual"}',
        timeout_s=3.0,
        context="simulator speed override",
    )

    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert {
        "method": requests[0].method,
        "body": requests[0].content,
    } == {
        "method": "PUT",
        "body": b'{"speed_source":"manual"}',
    }
    assert status == 200
    assert body == "ok"


def test_stream_http_response_maps_timeout_to_oserror(httpx_mock: HTTPXMock) -> None:
    url = "https://api.github.com/repos/owner/repo/releases/assets/1"
    add_httpx_exception(
        httpx_mock,
        url=url,
        exception=httpx.ReadTimeout("timed out"),
    )
    with pytest.raises(OSError, match="timed out"):
        with stream_http_response(
            url,
            timeout_s=30,
            context="release asset",
            require_https=True,
        ):
            pytest.fail("stream should not succeed")


def test_download_release_asset_streams_response_to_disk(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    url = "https://api.github.com/repos/owner/repo/releases/assets/1"
    add_bytes_response(httpx_mock, url=url, content=b"wheel-bytes")
    dest = tmp_path / "artifact.whl"

    download_release_asset(
        client=GitHubApiClient(),
        url=url,
        dest=dest,
        timeout_s=30.0,
        max_bytes=1024,
        chunk_size=4,
        size_limit_message="too large",
    )

    assert dest.read_bytes() == b"wheel-bytes"


def test_download_release_asset_maps_status_errors(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    url = "https://api.github.com/repos/owner/repo/releases/assets/1"
    add_text_response(httpx_mock, url=url, text="busy", status_code=503)

    with pytest.raises(OSError, match="HTTP 503"):
        download_release_asset(
            client=GitHubApiClient(),
            url=url,
            dest=tmp_path / "artifact.whl",
            timeout_s=30.0,
            max_bytes=1024,
            chunk_size=4,
            size_limit_message="too large",
        )


def test_download_release_asset_maps_connection_failures(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    url = "https://api.github.com/repos/owner/repo/releases/assets/1"
    add_httpx_exception(
        httpx_mock,
        url=url,
        exception=httpx.ConnectError("connection refused"),
    )

    with pytest.raises(OSError, match="connection refused"):
        download_release_asset(
            client=GitHubApiClient(),
            url=url,
            dest=tmp_path / "artifact.whl",
            timeout_s=30.0,
            max_bytes=1024,
            chunk_size=4,
            size_limit_message="too large",
        )


def test_download_release_asset_rejects_oversized_payload(
    httpx_mock: HTTPXMock, tmp_path: Path
) -> None:
    url = "https://api.github.com/repos/owner/repo/releases/assets/1"
    add_bytes_response(httpx_mock, url=url, content=b"0123456789")

    with pytest.raises(ValueError, match="too large"):
        download_release_asset(
            client=GitHubApiClient(),
            url=url,
            dest=tmp_path / "artifact.whl",
            timeout_s=30.0,
            max_bytes=4,
            chunk_size=2,
            size_limit_message="too large",
        )
