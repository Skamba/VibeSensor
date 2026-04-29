from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibesensor.use_cases.updates.firmware.firmware_cache import refresh_cache_cli
from vibesensor.use_cases.updates.releases.cli import fetch_latest_wheel_cli


def test_fetch_latest_wheel_cli_prints_release_and_downloaded_artifact(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    dest_dir = tmp_path / "downloads"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vibesensor-release-fetch",
            "--repo",
            "Skamba/VibeSensor",
            "--dest",
            str(dest_dir),
        ],
    )

    class _Fetcher:
        def __init__(self, config) -> None:
            assert config.server_repo == "Skamba/VibeSensor"

        def find_latest_release(self) -> object:
            return SimpleNamespace(
                tag="server-v2026.4.4",
                version="2026.4.4",
                sha256="a" * 64,
                asset_name="vibesensor-2026.4.4-py3-none-any.whl",
            )

        def download_wheel(self, release: object, dest_dir: str) -> Path:
            dest_path = Path(dest_dir)
            dest_path.mkdir(parents=True, exist_ok=True)
            wheel_path = dest_path / release.asset_name
            wheel_path.write_text("wheel", encoding="utf-8")
            return wheel_path

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.releases.cli.ServerReleaseFetcher",
        _Fetcher,
    )

    fetch_latest_wheel_cli()

    captured = capsys.readouterr()
    wheel_path = dest_dir / "vibesensor-2026.4.4-py3-none-any.whl"
    assert "Latest release: server-v2026.4.4 (2026.4.4)" in captured.out
    assert f"Downloaded: {wheel_path}" in captured.out
    assert f"SHA256: {'a' * 64}" in captured.out
    assert wheel_path.is_file()


def test_fetch_latest_wheel_cli_exits_for_operational_value_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-release-fetch"])

    class _BrokenFetcher:
        def __init__(self, _config) -> None:
            pass

        def find_latest_release(self) -> object:
            raise ValueError("bad release metadata")

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.releases.cli.ServerReleaseFetcher",
        _BrokenFetcher,
    )

    with pytest.raises(SystemExit, match="1"):
        fetch_latest_wheel_cli()

    captured = capsys.readouterr()
    assert "ERROR: bad release metadata" in captured.err


def test_fetch_latest_wheel_cli_allows_programmer_errors_to_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-release-fetch"])

    class _BrokenFetcher:
        def __init__(self, _config) -> None:
            pass

        def find_latest_release(self) -> object:
            raise AssertionError("programmer bug")

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.releases.cli.ServerReleaseFetcher",
        _BrokenFetcher,
    )

    with pytest.raises(AssertionError, match="programmer bug"):
        fetch_latest_wheel_cli()


def test_refresh_cache_cli_prints_refreshed_cache_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "firmware-cache"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vibesensor-fw-refresh",
            "--cache-dir",
            str(cache_dir),
            "--repo",
            "Skamba/VibeSensor",
            "--channel",
            "stable",
            "--tag",
            "server-v2026.4.4",
        ],
    )

    class _Cache:
        def __init__(self, config) -> None:
            assert config.cache_dir == str(cache_dir)
            assert config.firmware_repo == "Skamba/VibeSensor"
            assert config.channel == "stable"
            assert config.pinned_tag == "server-v2026.4.4"

        def refresh(self) -> object:
            return SimpleNamespace(
                tag="server-v2026.4.4",
                asset="server-v2026.4.4.zip",
                source="downloaded",
                sha256="b" * 64,
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.firmware_cache.FirmwareCache",
        _Cache,
    )

    refresh_cache_cli()

    captured = capsys.readouterr()
    assert (
        "Firmware cache refreshed: tag=server-v2026.4.4, asset=server-v2026.4.4.zip" in captured.out
    )
    assert f"Source: downloaded, SHA256: {'b' * 64}" in captured.out


def test_refresh_cache_cli_exits_for_operational_os_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-fw-refresh"])

    class _BrokenCache:
        def __init__(self, _config) -> None:
            pass

        def refresh(self) -> object:
            raise OSError("network down")

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.firmware_cache.FirmwareCache",
        _BrokenCache,
    )

    with pytest.raises(SystemExit, match="1"):
        refresh_cache_cli()

    captured = capsys.readouterr()
    assert "ERROR: Firmware cache refresh failed: network down" in captured.err


def test_refresh_cache_cli_allows_programmer_errors_to_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-fw-refresh"])

    class _BrokenCache:
        def __init__(self, _config) -> None:
            pass

        def refresh(self) -> object:
            raise AssertionError("programmer bug")

    monkeypatch.setattr(
        "vibesensor.use_cases.updates.firmware.firmware_cache.FirmwareCache",
        _BrokenCache,
    )

    with pytest.raises(AssertionError, match="programmer bug"):
        refresh_cache_cli()
