from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from vibesensor.update.firmware_cache import (
    FirmwareCacheConfig,
    GitHubReleaseFetcher,
    _safe_extractall,
)


def _make_fetcher(channel: str = "stable") -> GitHubReleaseFetcher:
    config = FirmwareCacheConfig(firmware_repo="Skamba/VibeSensor", channel=channel)
    return GitHubReleaseFetcher(config)


def _make_zip(entries: dict[str, str | bytes]) -> io.BytesIO:
    """Create an in-memory zip with *entries* mapping name -> content."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# find_release – channel preference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("channel", "expected_tag", "releases"),
    [
        pytest.param(
            "stable",
            "server-v2026.2.28",
            [
                {
                    "tag_name": "server-v2026.2.28",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "vibesensor-2026.2.28-py3-none-any.whl",
                            "url": "https://api.github.com/a",
                        },
                        {"name": "vibesensor-fw-v2026.2.28.zip", "url": "https://api.github.com/b"},
                    ],
                },
                {
                    "tag_name": "fw-v2026.2.27",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {"name": "vibesensor-fw-v2026.2.27.zip", "url": "https://api.github.com/b"},
                    ],
                },
            ],
            id="stable-prefers-combined",
        ),
        pytest.param(
            "prerelease",
            "server-v2026.2.28-rc1",
            [
                {
                    "tag_name": "server-v2026.2.28-rc1",
                    "draft": False,
                    "prerelease": True,
                    "assets": [
                        {
                            "name": "vibesensor-2026.2.28rc1-py3-none-any.whl",
                            "url": "https://api.github.com/a",
                        },
                        {
                            "name": "vibesensor-fw-v2026.2.28-rc1.zip",
                            "url": "https://api.github.com/b",
                        },
                    ],
                },
                {
                    "tag_name": "fw-v2026.2.28-rc1",
                    "draft": False,
                    "prerelease": True,
                    "assets": [
                        {
                            "name": "vibesensor-fw-v2026.2.28-rc1.zip",
                            "url": "https://api.github.com/c",
                        },
                    ],
                },
            ],
            id="prerelease-prefers-combined",
        ),
    ],
)
def test_find_release_prefers_combined_release_assets(
    channel: str,
    expected_tag: str,
    releases: list[dict],
) -> None:
    fetcher = _make_fetcher(channel)
    fetcher._api_get = lambda _url: releases  # type: ignore[method-assign]
    selected = fetcher.find_release()
    assert selected["tag_name"] == expected_tag


def test_find_release_raises_when_no_firmware_assets() -> None:
    fetcher = _make_fetcher()

    releases = [
        {
            "tag_name": "server-v2026.2.27",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "vibesensor-2026.2.27-py3-none-any.whl",
                    "url": "https://api.github.com/a",
                },
            ],
        },
    ]

    fetcher._api_get = lambda _url: releases  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="No eligible firmware release found"):
        fetcher.find_release()


# ---------------------------------------------------------------------------
# _safe_extractall
# ---------------------------------------------------------------------------


def test_safe_extractall_rejects_path_traversal(tmp_path: Path) -> None:
    """Zip entries with ``../`` segments must be rejected."""
    buf = _make_zip({"../../etc/passwd": "pwned"})
    dest = tmp_path / "extract"
    dest.mkdir()
    with (
        zipfile.ZipFile(buf) as zf,
        pytest.raises(ValueError, match="outside the target directory"),
    ):
        _safe_extractall(zf, dest)


def test_safe_extractall_allows_normal_entries(tmp_path: Path) -> None:
    """Normal zip entries must extract without error."""
    buf = _make_zip({"firmware/main.bin": b"\x00\x01\x02", "flash.json": '{"environments": []}'})
    dest = tmp_path / "extract"
    dest.mkdir()
    with zipfile.ZipFile(buf) as zf:
        _safe_extractall(zf, dest)
    assert (dest / "firmware" / "main.bin").is_file()
    assert (dest / "flash.json").is_file()
