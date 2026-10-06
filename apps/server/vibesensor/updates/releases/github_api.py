"""Shared GitHub REST API helpers for updater release fetchers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import msgspec

from vibesensor.updates.http_client import (
    build_get_request,
    read_typed_json_response,
)

DOWNLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB per read()
GITHUB_USER_AGENT = "VibeSensor-Updater"

__all__ = [
    "DOWNLOAD_CHUNK_BYTES",
    "GitHubApiAssetRecord",
    "GitHubApiClient",
    "GitHubApiReleaseRecord",
    "github_api_headers",
]


def github_api_headers(
    token: str = "",
    *,
    accept: str = "application/vnd.github+json",
) -> dict[str, str]:
    """Build standard GitHub REST API request headers."""

    headers: dict[str, str] = {
        "Accept": accept,
        "User-Agent": GITHUB_USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class GitHubApiAssetRecord(msgspec.Struct, kw_only=True, frozen=True):
    name: str
    url: str
    digest: str = ""


class GitHubApiReleaseRecord(msgspec.Struct, kw_only=True, frozen=True):
    tag_name: str
    draft: bool
    prerelease: bool
    assets: list[GitHubApiAssetRecord]
    published_at: str = ""


@dataclass(frozen=True, slots=True)
class GitHubApiClient:
    """Shared GitHub REST API client used by updater fetchers."""

    token: str = ""
    context: str = "github"
    transport: httpx.BaseTransport | None = None

    def api_headers(self, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return github_api_headers(self.token, accept=accept)

    def build_request(
        self,
        url: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> httpx.Request:
        return build_get_request(
            url,
            headers=self.api_headers(accept=accept),
            context=self.context,
            require_https=True,
        )

    def get_typed_json(self, url: str, *, response_type: Any) -> Any:
        """GET *url* and decode the JSON response into *response_type* via msgspec."""

        return read_typed_json_response(
            url,
            response_type=response_type,
            headers=self.api_headers(),
            timeout_s=30,
            context=self.context,
            require_https=True,
            transport=self.transport,
        )
