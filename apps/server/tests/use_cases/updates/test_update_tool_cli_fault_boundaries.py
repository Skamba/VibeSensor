from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vibesensor.use_cases.updates.firmware.firmware_cache import refresh_cache_cli
from vibesensor.use_cases.updates.releases.release_fetcher import fetch_latest_wheel_cli


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
        "vibesensor.use_cases.updates.releases.release_fetcher.ServerReleaseFetcher",
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
        "vibesensor.use_cases.updates.releases.release_fetcher.ServerReleaseFetcher",
        _BrokenFetcher,
    )

    with pytest.raises(AssertionError, match="programmer bug"):
        fetch_latest_wheel_cli()


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
