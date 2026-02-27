from __future__ import annotations

from vibesensor.firmware_cache import FirmwareCacheConfig, GitHubReleaseFetcher


def test_find_release_stable_skips_non_firmware_assets() -> None:
    config = FirmwareCacheConfig(firmware_repo="Skamba/VibeSensor", channel="stable")
    fetcher = GitHubReleaseFetcher(config)

    releases = [
        {
            "tag_name": "server-v2026.2.27",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "vibesensor-2026.2.27-py3-none-any.whl", "url": "https://api.github.com/a"}
            ],
        },
        {
            "tag_name": "fw-v2026.2.27",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "vibesensor-fw-v2026.2.27.zip", "url": "https://api.github.com/b"}
            ],
        },
    ]

    fetcher._api_get = lambda _url: releases  # type: ignore[method-assign]
    selected = fetcher.find_release()
    assert selected["tag_name"] == "fw-v2026.2.27"


def test_find_release_prerelease_skips_non_firmware_assets() -> None:
    config = FirmwareCacheConfig(firmware_repo="Skamba/VibeSensor", channel="prerelease")
    fetcher = GitHubReleaseFetcher(config)

    releases = [
        {
            "tag_name": "server-v2026.2.28-rc1",
            "draft": False,
            "prerelease": True,
            "assets": [
                {"name": "vibesensor-2026.2.28rc1-py3-none-any.whl", "url": "https://api.github.com/a"}
            ],
        },
        {
            "tag_name": "fw-v2026.2.28-rc1",
            "draft": False,
            "prerelease": True,
            "assets": [
                {"name": "vibesensor-fw-v2026.2.28-rc1.zip", "url": "https://api.github.com/b"}
            ],
        },
    ]

    fetcher._api_get = lambda _url: releases  # type: ignore[method-assign]
    selected = fetcher.find_release()
    assert selected["tag_name"] == "fw-v2026.2.28-rc1"


def test_find_release_raises_when_no_firmware_assets() -> None:
    config = FirmwareCacheConfig(firmware_repo="Skamba/VibeSensor", channel="stable")
    fetcher = GitHubReleaseFetcher(config)

    releases = [
        {
            "tag_name": "server-v2026.2.27",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "vibesensor-2026.2.27-py3-none-any.whl", "url": "https://api.github.com/a"}
            ],
        }
    ]

    fetcher._api_get = lambda _url: releases  # type: ignore[method-assign]

    try:
        fetcher.find_release()
    except ValueError as exc:
        msg = str(exc)
        assert "No eligible firmware release found" in msg
    else:
        raise AssertionError("Expected ValueError when no firmware assets are present")
