"""Shared GitHub REST API helpers for updater release fetchers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import Request, urlopen

from vibesensor.shared.types.json_types import JsonValue

DOWNLOAD_CHUNK_BYTES = 1024 * 1024  # 1 MB per read()

__all__ = [
    "DOWNLOAD_CHUNK_BYTES",
    "GitHubApiClient",
    "github_api_headers",
    "validate_https_url",
]


def validate_https_url(url: str, *, context: str = "operation") -> None:
    """Raise ``ValueError`` if *url* does not use the HTTPS scheme."""

    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS URL for {context}: {url}")


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

    def api_headers(self, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
        return github_api_headers(self.token, accept=accept)

    def build_request(
        self,
        url: str,
        *,
        accept: str = "application/vnd.github+json",
    ) -> Request:
        validate_https_url(url, context=self.context)
        return Request(url, headers=self.api_headers(accept=accept))

    def get_json(self, url: str) -> JsonValue:
        """GET *url* and return the parsed JSON response."""

        with urlopen(self.build_request(url), timeout=30) as resp:
            result: JsonValue = json.loads(resp.read().decode("utf-8"))
            return result
