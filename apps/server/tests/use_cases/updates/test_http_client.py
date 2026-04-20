from __future__ import annotations

import httpx
import pytest

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


def test_github_api_client_get_json_decodes_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept"] == "application/vnd.github+json"
        return httpx.Response(200, json={"ok": True}, request=request)

    client = GitHubApiClient(transport=httpx.MockTransport(handler))

    assert client.get_json("https://api.github.com/repos/owner/repo/releases") == {"ok": True}


def test_github_api_client_get_json_maps_non_200_to_oserror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy", request=request)

    client = GitHubApiClient(transport=httpx.MockTransport(handler))

    with pytest.raises(OSError, match="HTTP 503"):
        client.get_json("https://api.github.com/repos/owner/repo/releases")


def test_github_api_client_get_json_rejects_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not-json", request=request)

    client = GitHubApiClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ValueError, match="invalid JSON"):
        client.get_json("https://api.github.com/repos/owner/repo/releases")


def test_read_text_response_returns_status_and_body_for_local_smoke_checks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:8000/api/health"
        return httpx.Response(
            503,
            headers={"Content-Type": "text/plain; charset=utf-8"},
            text="booting",
            request=request,
        )

    status, content_type, body = read_text_response(
        "http://127.0.0.1:8000/api/health",
        timeout_s=3.0,
        context="release smoke",
        transport=httpx.MockTransport(handler),
    )

    assert status == 503
    assert content_type == "text/plain; charset=utf-8"
    assert body == "booting"


def test_read_text_response_supports_put_with_request_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["body"] = request.content
        return httpx.Response(200, text="ok", request=request)

    status, _content_type, body = read_text_response(
        "http://127.0.0.1:8000/api/settings/speed-source",
        method="PUT",
        headers={"Content-Type": "application/json"},
        content=b'{"speed_source":"manual"}',
        timeout_s=3.0,
        context="simulator speed override",
        transport=httpx.MockTransport(handler),
    )

    assert captured == {
        "method": "PUT",
        "body": b'{"speed_source":"manual"}',
    }
    assert status == 200
    assert body == "ok"


def test_stream_http_response_maps_timeout_to_oserror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(OSError, match="timed out"):
        with stream_http_response(
            "https://api.github.com/repos/owner/repo/releases/assets/1",
            timeout_s=30,
            context="release asset",
            require_https=True,
            transport=httpx.MockTransport(handler),
        ):
            pytest.fail("stream should not succeed")
