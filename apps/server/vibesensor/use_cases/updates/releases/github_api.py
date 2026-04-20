"""Shared GitHub REST API helpers for updater release fetchers."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from vibesensor.shared.types.json_types import JsonValue
from vibesensor.use_cases.updates.http_client import build_get_request, read_json_response

DOWNLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB per read()

__all__ = [
    "DOWNLOAD_CHUNK_BYTES",
    "GitHubApiClient",
    "github_api_headers",
    "validate_https_url",
]


def validate_https_url(url: str, *, context: str = "operation") -> None:
    """Raise ``ValueError`` if *url* does not use the HTTPS scheme."""

    build_get_request(url, context=context, require_https=True)


def github_api_headers(
    token: str = "",
    *,
    accept: str = "application/vnd.github+json",
) -> dict[str, str]:
    """Build standard GitHub REST API request headers."""

    headers: dict[str, str] = {"Accept": accept}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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

    def get_json(self, url: str) -> JsonValue:
        """GET *url* and return the parsed JSON response."""

        return read_json_response(
            url,
            headers=self.api_headers(),
            timeout_s=30,
            context=self.context,
            require_https=True,
            transport=self.transport,
        )
