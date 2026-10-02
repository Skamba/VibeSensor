from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from vibesensor.updates.firmware.firmware_cache import refresh_cache_cli
from vibesensor.updates.releases.cli import fetch_latest_wheel_cli


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
        "vibesensor.updates.releases.cli.ServerReleaseFetcher",
        _Fetcher,
    )

    fetch_latest_wheel_cli()

    captured = capsys.readouterr()
    wheel_path = dest_dir / "vibesensor-2026.4.4-py3-none-any.whl"
    assert "Latest release: server-v2026.4.4 (2026.4.4)" in captured.out
    assert f"Downloaded: {wheel_path}" in captured.out
    assert f"SHA256: {'a' * 64}" in captured.out
    assert wheel_path.is_file()


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
        "vibesensor.updates.firmware.firmware_cache.FirmwareCache",
        _Cache,
    )

    refresh_cache_cli()

    captured = capsys.readouterr()
    assert (
        "Firmware cache refreshed: tag=server-v2026.4.4, asset=server-v2026.4.4.zip" in captured.out
    )
    assert f"Source: downloaded, SHA256: {'b' * 64}" in captured.out


_FETCH_CLI = (
    fetch_latest_wheel_cli,
    "vibesensor.updates.releases.cli.ServerReleaseFetcher",
    "find_latest_release",
)
_REFRESH_CLI = (
    refresh_cache_cli,
    "vibesensor.updates.firmware.firmware_cache.FirmwareCache",
    "refresh",
)


@pytest.mark.parametrize(
    ("cli", "error", "expected_stderr"),
    [
        pytest.param(
            _FETCH_CLI,
            ValueError("bad release metadata"),
            "ERROR: bad release metadata",
            id="fetch-operational-value-error-exits",
        ),
        pytest.param(
            _REFRESH_CLI,
            OSError("network down"),
            "ERROR: Firmware cache refresh failed: network down",
            id="refresh-operational-os-error-exits",
        ),
        pytest.param(
            _FETCH_CLI, AssertionError("programmer bug"), None, id="fetch-programmer-error-surfaces"
        ),
        pytest.param(
            _REFRESH_CLI,
            AssertionError("programmer bug"),
            None,
            id="refresh-programmer-error-surfaces",
        ),
    ],
)
def test_update_tool_cli_fault_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cli: tuple[Callable[[], None], str, str],
    error: Exception,
    expected_stderr: str | None,
) -> None:
    """Operational errors exit 1 with a message; programmer errors propagate unchanged."""
    entrypoint, collaborator_path, failing_method = cli
    monkeypatch.setattr(sys, "argv", ["vibesensor-cli"])

    def _raise(self: object) -> object:
        raise error

    broken = type("_Broken", (), {"__init__": lambda self, _config: None, failing_method: _raise})
    monkeypatch.setattr(collaborator_path, broken)

    if expected_stderr is None:
        with pytest.raises(type(error), match=str(error)):
            entrypoint()
        return
    with pytest.raises(SystemExit, match="1"):
        entrypoint()
    assert expected_stderr in capsys.readouterr().err
