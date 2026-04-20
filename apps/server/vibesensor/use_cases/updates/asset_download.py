"""Common streaming asset download helpers for updater release fetchers."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Protocol

from vibesensor.use_cases.updates.http_client import stream_http_response

__all__ = ["download_release_asset"]


class GitHubAssetHeadersClient(Protocol):
    def api_headers(self, *, accept: str = "") -> dict[str, str]: ...


def download_release_asset(
    *,
    client: GitHubAssetHeadersClient,
    url: str,
    dest: Path,
    timeout_s: float,
    max_bytes: int,
    chunk_size: int,
    size_limit_message: str,
    temp_suffix: str = ".dl_tmp",
) -> None:
    """Stream a GitHub release asset to *dest* with temp-file cleanup and a size bound."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    with stream_http_response(
        url,
        headers=client.api_headers(accept="application/octet-stream"),
        timeout_s=timeout_s,
        context="release asset",
        require_https=True,
    ) as resp:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=temp_suffix)
        fdopen_ok = False
        downloaded = False
        try:
            total = 0
            with os.fdopen(tmp_fd, "wb") as tmp_f:
                fdopen_ok = True
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(size_limit_message)
                    tmp_f.write(chunk)
            Path(tmp_path).replace(dest)
            downloaded = True
        finally:
            if not fdopen_ok:
                with contextlib.suppress(OSError):
                    os.close(tmp_fd)
            if not downloaded:
                with contextlib.suppress(OSError):
                    Path(tmp_path).unlink()
