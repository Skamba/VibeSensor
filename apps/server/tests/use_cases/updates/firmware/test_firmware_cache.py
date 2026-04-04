from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibesensor.use_cases.updates.firmware.firmware_bundle import safe_extractall
from vibesensor.use_cases.updates.firmware.firmware_release_fetcher import GitHubReleaseFetcher
from vibesensor.use_cases.updates.firmware.firmware_types import FirmwareCacheConfig
from vibesensor.use_cases.updates.releases.github_api import GitHubApiClient


def _make_fetcher(
    channel: str = "stable",
    *,
    client: GitHubApiClient | None = None,
) -> GitHubReleaseFetcher:
    config = FirmwareCacheConfig(firmware_repo="Skamba/VibeSensor", channel=channel)
    return GitHubReleaseFetcher(config, client=client)


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
    client = MagicMock(spec=GitHubApiClient)
    client.get_json.return_value = releases
    fetcher = _make_fetcher(channel, client=client)
    selected = fetcher.find_release()
    assert selected["tag_name"] == expected_tag


def test_find_release_raises_when_no_firmware_assets() -> None:
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

    client = MagicMock(spec=GitHubApiClient)
    client.get_json.return_value = releases
    fetcher = _make_fetcher(client=client)

    with pytest.raises(ValueError, match="No eligible firmware release found"):
        fetcher.find_release()


# ---------------------------------------------------------------------------
# safe_extractall
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
        safe_extractall(zf, dest)


def test_safe_extractall_allows_normal_entries(tmp_path: Path) -> None:
    """Normal zip entries must extract without error."""
    buf = _make_zip({"firmware/main.bin": b"\x00\x01\x02", "flash.json": '{"environments": []}'})
    dest = tmp_path / "extract"
    dest.mkdir()
    with zipfile.ZipFile(buf) as zf:
        safe_extractall(zf, dest)
    assert (dest / "firmware" / "main.bin").is_file()
    assert (dest / "flash.json").is_file()
