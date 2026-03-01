from __future__ import annotations

from pathlib import Path

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
            "assets": [{"name": "vibesensor-fw-v2026.2.27.zip", "url": "https://api.github.com/b"}],
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
                {
                    "name": "vibesensor-2026.2.28rc1-py3-none-any.whl",
                    "url": "https://api.github.com/a",
                }
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


def test_safe_extractall_rejects_path_traversal(tmp_path: Path) -> None:
    """Zip entries with ``../`` segments must be rejected."""
    import io
    import zipfile

    from vibesensor.firmware_cache import _safe_extractall

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "pwned")
    buf.seek(0)

    dest = tmp_path / "extract"
    dest.mkdir()
    with zipfile.ZipFile(buf) as zf:
        try:
            _safe_extractall(zf, dest)
        except ValueError as exc:
            assert "outside the target directory" in str(exc)
        else:
            raise AssertionError("Expected ValueError for path traversal zip entry")


def test_safe_extractall_allows_normal_entries(tmp_path: Path) -> None:
    """Normal zip entries must extract without error."""
    import io
    import zipfile

    from vibesensor.firmware_cache import _safe_extractall

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("firmware/main.bin", b"\x00\x01\x02")
        zf.writestr("flash.json", '{"environments": []}')
    buf.seek(0)

    dest = tmp_path / "extract"
    dest.mkdir()
    with zipfile.ZipFile(buf) as zf:
        _safe_extractall(zf, dest)
    assert (dest / "firmware" / "main.bin").is_file()
    assert (dest / "flash.json").is_file()
