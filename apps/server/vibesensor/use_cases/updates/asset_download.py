"""Common streaming asset download helpers for updater release fetchers."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

__all__ = ["download_release_asset"]


class GitHubAssetRequestBuilder(Protocol):
    def build_request(self, url: str, *, accept: str = "") -> Request: ...


def download_release_asset(
    *,
    client: GitHubAssetRequestBuilder,
    url: str,
    dest: Path,
    timeout_s: float,
    max_bytes: int,
    chunk_size: int,
    size_limit_message: str,
    temp_suffix: str = ".dl_tmp",
) -> None:
    """Stream a GitHub release asset to *dest* with temp-file cleanup and a size bound."""

    req = client.build_request(url, accept="application/octet-stream")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urlopen(req, timeout=timeout_s) as resp:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), suffix=temp_suffix)
        fdopen_ok = False
        downloaded = False
        try:
            total = 0
            with os.fdopen(tmp_fd, "wb") as tmp_f:
                fdopen_ok = True
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
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
