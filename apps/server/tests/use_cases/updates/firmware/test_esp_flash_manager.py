from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from test_support import response_payload
from test_support.firmware_bundles import write_firmware_bundle

from vibesensor.adapters.http.updates import create_update_routes
from vibesensor.shared.exceptions import ConfigurationError, UpdateError
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.firmware.esp_flash_types import (
    FlashCommandRunner,
    SerialPortInfo,
    SerialPortProvider,
)
from vibesensor.use_cases.updates.firmware.firmware_cache import FirmwareCache
from vibesensor.use_cases.updates.firmware.firmware_types import FirmwareCacheConfig

# ── Constants ──

_DEFAULT_PORT = SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")


# ── Test doubles ──


class _FakePorts(SerialPortProvider):
    def __init__(self, ports: list[SerialPortInfo]) -> None:
        self._ports = ports

    async def list_ports(self) -> list[SerialPortInfo]:
        return list(self._ports)


class _FakeRunner(FlashCommandRunner):
    def __init__(
        self,
        *,
        hang: bool = False,
        fail_erase: bool = False,
        fail_write: bool = False,
        raise_os_error: bool = False,
    ) -> None:
        self.calls: list[list[str]] = []
        self.call_cwds: list[str] = []
        self.hang = hang
        self.fail_erase = fail_erase
        self.fail_write = fail_write
        self.raise_os_error = raise_os_error

    async def run(
        self,
        args: list[str],
        *,
        cwd: str,
        line_cb,
        cancel_event: asyncio.Event,
        timeout_s: float | None = None,
    ) -> int:
        self.calls.append(list(args))
        self.call_cwds.append(str(cwd))
        line_cb(f"running {' '.join(args)}")
        if self.raise_os_error:
            raise OSError("serial port disappeared")
        if self.hang:
            while not cancel_event.is_set():
                await asyncio.sleep(0.05)
            return 130
        if self.fail_erase and "erase_flash" in args:
            line_cb("HTTPClientError: ")
            return 1
        if self.fail_write and "write_flash" in args:
            return 1
        return 0


# ── Helpers ──


def _assert_no_platformio_invocation(calls: list[list[str]]) -> None:
    for call in calls:
        cmd_name = Path(call[0]).name.lower() if call else ""
        assert cmd_name not in {"pio", "platformio"}, f"PlatformIO invoked: {call}"
        if len(call) > 2:
            assert call[1:3] != ["-m", "platformio"], f"PlatformIO module invoked: {call}"


def _make_cache(tmp_path: Path, *, with_current: bool = False, with_baseline: bool = False) -> Path:
    """Create a firmware cache directory with optional current/baseline bundles."""
    cache_dir = tmp_path / "fw-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if with_current:
        write_firmware_bundle(cache_dir / "current")
        meta = {
            "tag": "fw-main-abc1234",
            "asset": "vibesensor-fw-main-abc1234.zip",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sha256": "abc123",
            "source": "downloaded",
        }
        (cache_dir / "current" / "_meta.json").write_text(
            json.dumps(meta, indent=2),
            encoding="utf-8",
        )
    if with_baseline:
        write_firmware_bundle(cache_dir / "baseline")
        meta = {
            "tag": "baseline",
            "asset": "embedded",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sha256": "baseline123",
            "source": "baseline",
        }
        (cache_dir / "baseline" / "_meta.json").write_text(
            json.dumps(meta, indent=2),
            encoding="utf-8",
        )
    return cache_dir


def _firmware_cache(cache_dir: Path) -> FirmwareCache:
    """Wrap a cache directory path into a ``FirmwareCache`` instance."""
    return FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))


def _build_manager(
    cache_dir: Path,
    *,
    runner: _FakeRunner | None = None,
    ports: list[SerialPortInfo] | None = None,
) -> tuple[EspFlashManager, _FakeRunner]:
    """Build an ``EspFlashManager`` with sensible defaults for testing."""
    if runner is None:
        runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts(ports or [_DEFAULT_PORT]),
        firmware_cache=_firmware_cache(cache_dir),
    )
    return mgr, runner


def _route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {path} [{method}]")


# ── Fixtures ──


@pytest.fixture
def _patch_esptool_which(monkeypatch) -> None:
    """Patch ``shutil.which`` so ``esptool.py`` resolves to a fake path."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )


def test_cache_active_bundle_uses_current_over_baseline(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True, with_baseline=True)
    assert _firmware_cache(cache_dir).active_bundle_dir() == cache_dir / "current"


def test_cache_falls_back_to_baseline_when_no_current(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=False, with_baseline=True)
    assert _firmware_cache(cache_dir).active_bundle_dir() == cache_dir / "baseline"


def test_cache_returns_none_when_empty(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path)
    assert _firmware_cache(cache_dir).active_bundle_dir() is None


def test_cache_falls_back_when_current_is_invalid(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True, with_baseline=True)
    (cache_dir / "current" / "flash.json").unlink()
    assert _firmware_cache(cache_dir).active_bundle_dir() == cache_dir / "baseline"


def test_cache_info_reports_source_and_tag(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    info = _firmware_cache(cache_dir).info()
    assert info["status"] == "ok"
    assert info["source"] == "downloaded"
    assert info["tag"] == "fw-main-abc1234"


def test_cache_info_no_firmware(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path)
    assert _firmware_cache(cache_dir).info()["status"] == "no_firmware"


def test_cache_info_reports_corrupt_metadata_explicitly(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    (cache_dir / "current" / "_meta.json").write_text("{not-json", encoding="utf-8")

    info = _firmware_cache(cache_dir).info()

    assert info["status"] == "metadata_invalid"
    assert info["source"] == "downloaded"
    assert "metadata is corrupt" in info["message"]


# ── Flash Manager Tests (using cached bundles) ──


@pytest.mark.asyncio
async def test_port_discovery_returns_metadata(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    rich_port = SerialPortInfo(
        port="/dev/ttyUSB0",
        description="USB UART",
        vid=6790,
        pid=29987,
        serial_number="abc",
    )
    mgr, _ = _build_manager(cache_dir, ports=[rich_port])
    ports = await mgr.list_ports()
    assert ports == [
        {
            "port": "/dev/ttyUSB0",
            "description": "USB UART",
            "vid": 6790,
            "pid": 29987,
            "serial_number": "abc",
        },
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_job_uses_cached_bundle_manifest(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, runner = _build_manager(cache_dir)

    mgr.start(port=None, auto_detect=True)
    assert mgr.status.state.value == "running"
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert mgr.status.phase == "done"
    assert mgr.status.last_success_at == mgr.status.finished_at
    assert any("erase_flash" in call for call in runner.calls)
    assert any("write_flash" in call for call in runner.calls)
    assert mgr.history()[0]["state"] == "success"

    # Verify manifest-driven offsets are used
    write_call = [c for c in runner.calls if "write_flash" in c][0]
    assert "0x10000" in write_call
    assert "0x1000" in write_call
    assert "0x8000" in write_call
    assert any("firmware.bin" in arg for arg in write_call)
    _assert_no_platformio_invocation(runner.calls)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_fails_fast_when_no_firmware_available(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path)
    mgr, _ = _build_manager(cache_dir)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert "No firmware bundle available" in str(mgr.status.error)
    assert any("updater" in line.lower() for line in mgr.logs_since(after=0)["lines"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_fails_when_bundle_metadata_is_corrupt(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    (cache_dir / "current" / "_meta.json").write_text("{not-json", encoding="utf-8")
    mgr, runner = _build_manager(cache_dir)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task

    assert mgr.status.state.value == "failed"
    assert "metadata is corrupt" in str(mgr.status.error)
    assert not any("erase_flash" in call for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_single_job_lock_and_cancel(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, _ = _build_manager(cache_dir, runner=_FakeRunner(hang=True))

    mgr.start(port=None, auto_detect=True)
    with pytest.raises(UpdateError, match="already in progress"):
        mgr.start(port="/dev/ttyUSB0", auto_detect=False)
    assert mgr.cancel() is True
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "cancelled"
    assert mgr.status.phase == "cancelled"
    assert mgr.history()[0]["state"] == "cancelled"
    assert mgr.history()[0]["error"] == "Flash cancelled by user"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_multiple_ports_without_choice_fails_actionably(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    two_ports = [
        SerialPortInfo(port="/dev/ttyUSB0", description="USB A"),
        SerialPortInfo(port="/dev/ttyUSB1", description="USB B"),
    ]
    mgr, _ = _build_manager(cache_dir, ports=two_ports)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert "Multiple serial ports" in str(mgr.status.error)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_esp_flash_api_lifecycle(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, _ = _build_manager(cache_dir)

    router = create_update_routes(None, mgr)
    start_ep = _route_endpoint(router, "/api/esp-flash/start", "POST")
    status_ep = _route_endpoint(router, "/api/esp-flash/status", "GET")
    logs_ep = _route_endpoint(router, "/api/esp-flash/logs", "GET")
    cancel_ep = _route_endpoint(router, "/api/esp-flash/cancel", "POST")
    history_ep = _route_endpoint(router, "/api/esp-flash/history", "GET")

    await start_ep(type("Req", (), {"port": None, "auto_detect": True})())
    assert mgr._task is not None
    await mgr._task
    assert response_payload(await status_ep())["state"] == "success"
    assert response_payload(await logs_ep(after=0))["next_index"] >= 1
    assert response_payload(await cancel_ep()) == {"cancelled": False}
    assert len(response_payload(await history_ep())["attempts"]) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_esp_flash_api_rejects_concurrent_start(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, _ = _build_manager(cache_dir, runner=_FakeRunner(hang=True))

    router = create_update_routes(None, mgr)
    start_ep = _route_endpoint(router, "/api/esp-flash/start", "POST")

    req = type("Req", (), {"port": None, "auto_detect": True})()
    await start_ep(req)
    with pytest.raises(HTTPException) as exc_info:
        await start_ep(req)
    assert exc_info.value.status_code == 409
    mgr.cancel()
    assert mgr._task is not None
    await mgr._task


@pytest.mark.asyncio
async def test_flash_uses_python_module_fallback_when_esptool_binary_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: SimpleNamespace() if name == "esptool" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, runner = _build_manager(cache_dir)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert any(call[1:3] == ["-m", "esptool"] for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_fails_when_esptool_erase_step_fails(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, runner = _build_manager(cache_dir, runner=_FakeRunner(fail_erase=True))

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert mgr.status.phase == "failed"
    assert mgr.status.error == "Flash erase step failed"
    assert mgr.status.to_dict()["phase"] == "failed"
    assert mgr.history()[0]["state"] == "failed"
    assert mgr.history()[0]["error"] == "Flash erase step failed"
    assert any("erase_flash" in " ".join(call) for call in runner.calls)
    assert not any("write_flash" in " ".join(call) for call in runner.calls)


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_fails_cleanly_for_operational_os_errors(tmp_path: Path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, _runner = _build_manager(cache_dir, runner=_FakeRunner(raise_os_error=True))

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert mgr.status.error == "Flash failed: serial port disappeared"
    assert "serial port disappeared" in " ".join(mgr.logs_since(after=0)["lines"])


@pytest.mark.asyncio
@pytest.mark.usefixtures("_patch_esptool_which")
async def test_flash_no_network_access_in_flash_path(tmp_path: Path, monkeypatch) -> None:
    """Flashing must not make any network requests."""
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr, _ = _build_manager(cache_dir)

    def _block_network(*args, **kwargs):
        raise AssertionError("Network access during flashing is not allowed")

    monkeypatch.setattr("urllib.request.urlopen", _block_network)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"


# ---------------------------------------------------------------------------
# EspFlashStartRequest model validation (moved from test_api_response_models)
# ---------------------------------------------------------------------------


def test_esp_flash_start_request_requires_port_when_not_auto_detect() -> None:
    """EspFlashStartRequest must reject auto_detect=False with no port."""
    from pydantic import ValidationError

    from vibesensor.adapters.http.models import EspFlashStartRequest

    with pytest.raises(ValidationError):
        EspFlashStartRequest(port=None, auto_detect=False)

    with pytest.raises(ValidationError):
        EspFlashStartRequest(port="", auto_detect=False)

    # Valid: auto_detect=False with explicit port
    req = EspFlashStartRequest(port="/dev/ttyUSB0", auto_detect=False)
    assert req.port == "/dev/ttyUSB0"

    # Valid: auto_detect=True without port
    req = EspFlashStartRequest(port=None, auto_detect=True)
    assert req.auto_detect is True


@pytest.mark.asyncio
async def test_esp_flash_start_returns_400_on_configuration_error() -> None:
    """start_esp_flash must map ConfigurationError from esp_flash_manager.start → 400."""
    from unittest.mock import MagicMock

    from vibesensor.adapters.http.updates import create_update_routes

    class _ValErrFlashManager:
        async def list_ports(self):
            return []

        def start(self, **_):
            raise ConfigurationError("port is required when auto_detect is False")

        def cancel(self):
            return False

        def logs_since(self, _after):
            return {"lines": [], "next_after": 0}

        def history(self):
            return []

        @property
        def status(self):
            return type("S", (), {"to_dict": lambda self: {}})()

    state = MagicMock()
    state.esp_flash_manager = _ValErrFlashManager()
    router = create_update_routes(state.update_manager, state.esp_flash_manager)

    start_endpoint = None
    for route in router.routes:
        path_match = getattr(route, "path", "") == "/api/esp-flash/start"
        method_match = "POST" in getattr(route, "methods", set())
        if path_match and method_match:
            start_endpoint = route.endpoint
            break
    assert start_endpoint is not None

    req = type("R", (), {"port": None, "auto_detect": False})()
    with pytest.raises(HTTPException) as exc_info:
        await start_endpoint(req)
    assert exc_info.value.status_code == 400
