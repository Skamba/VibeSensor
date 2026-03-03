from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from vibesensor.api import create_router
from vibesensor.esp_flash_manager import (
    EspFlashManager,
    FlashCommandRunner,
    SerialPortInfo,
    SerialPortProvider,
)
from vibesensor.firmware_cache import (
    FirmwareCache,
    FirmwareCacheConfig,
    validate_bundle,
)


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
    ) -> None:
        self.calls: list[list[str]] = []
        self.call_cwds: list[str] = []
        self.hang = hang
        self.fail_erase = fail_erase
        self.fail_write = fail_write

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


def _make_bundle(bundle_dir: Path) -> None:
    """Create a valid firmware bundle with flash.json manifest and binaries."""
    env_dir = bundle_dir / "m5stack_atom"
    env_dir.mkdir(parents=True, exist_ok=True)
    bins = {}
    for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
        content = f"fake-{name}".encode()
        (env_dir / name).write_bytes(content)
        bins[name] = hashlib.sha256(content).hexdigest()
    manifest = {
        "generated_from": "test",
        "environments": [
            {
                "name": "m5stack_atom",
                "segments": [
                    {
                        "file": "m5stack_atom/firmware.bin",
                        "offset": "0x10000",
                        "sha256": bins["firmware.bin"],
                    },
                    {
                        "file": "m5stack_atom/bootloader.bin",
                        "offset": "0x1000",
                        "sha256": bins["bootloader.bin"],
                    },
                    {
                        "file": "m5stack_atom/partitions.bin",
                        "offset": "0x8000",
                        "sha256": bins["partitions.bin"],
                    },
                ],
            }
        ],
    }
    (bundle_dir / "flash.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _make_cache(tmp_path: Path, *, with_current: bool = False, with_baseline: bool = False):
    """Create a firmware cache directory with optional current/baseline bundles."""
    cache_dir = tmp_path / "fw-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    if with_current:
        _make_bundle(cache_dir / "current")
        meta = {
            "tag": "fw-main-abc1234",
            "asset": "vibesensor-fw-main-abc1234.zip",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sha256": "abc123",
            "source": "downloaded",
        }
        (cache_dir / "current" / "_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    if with_baseline:
        _make_bundle(cache_dir / "baseline")
        meta = {
            "tag": "baseline",
            "asset": "embedded",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "sha256": "baseline123",
            "source": "baseline",
        }
        (cache_dir / "baseline" / "_meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    return cache_dir


# ── Firmware Cache Tests ──


def test_validate_bundle_succeeds(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    _make_bundle(bundle_dir)
    manifest = validate_bundle(bundle_dir)
    assert len(manifest.environments) == 1
    assert manifest.environments[0].name == "m5stack_atom"


def test_validate_bundle_fails_missing_manifest(tmp_path) -> None:
    bundle_dir = tmp_path / "empty"
    bundle_dir.mkdir()
    with pytest.raises(ValueError, match="missing manifest"):
        validate_bundle(bundle_dir)


def test_validate_bundle_fails_missing_binary(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    _make_bundle(bundle_dir)
    (bundle_dir / "m5stack_atom" / "firmware.bin").unlink()
    with pytest.raises(ValueError, match="missing referenced binary"):
        validate_bundle(bundle_dir)


def test_validate_bundle_fails_checksum_mismatch(tmp_path) -> None:
    bundle_dir = tmp_path / "bundle"
    _make_bundle(bundle_dir)
    (bundle_dir / "m5stack_atom" / "firmware.bin").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        validate_bundle(bundle_dir)


def test_cache_active_bundle_uses_current_over_baseline(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True, with_baseline=True)
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    active = cache.active_bundle_dir()
    assert active is not None
    assert active == cache_dir / "current"


def test_cache_falls_back_to_baseline_when_no_current(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=False, with_baseline=True)
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    active = cache.active_bundle_dir()
    assert active is not None
    assert active == cache_dir / "baseline"


def test_cache_returns_none_when_empty(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=False, with_baseline=False)
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    assert cache.active_bundle_dir() is None


def test_cache_falls_back_when_current_is_invalid(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True, with_baseline=True)
    # Corrupt the current bundle
    (cache_dir / "current" / "flash.json").unlink()
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    active = cache.active_bundle_dir()
    assert active == cache_dir / "baseline"


def test_cache_info_reports_source_and_tag(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    info = cache.info()
    assert info["status"] == "ok"
    assert info["source"] == "downloaded"
    assert info["tag"] == "fw-main-abc1234"


def test_cache_info_no_firmware(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path)
    cache = FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir)))
    info = cache.info()
    assert info["status"] == "no_firmware"


# ── Flash Manager Tests (using cached bundles) ──


@pytest.mark.asyncio
async def test_port_discovery_returns_metadata(tmp_path) -> None:
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts(
            [
                SerialPortInfo(
                    port="/dev/ttyUSB0",
                    description="USB UART",
                    vid=6790,
                    pid=29987,
                    serial_number="abc",
                )
            ]
        ),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    ports = await mgr.list_ports()
    assert ports == [
        {
            "port": "/dev/ttyUSB0",
            "description": "USB UART",
            "vid": 6790,
            "pid": 29987,
            "serial_number": "abc",
        }
    ]


@pytest.mark.asyncio
async def test_flash_job_uses_cached_bundle_manifest(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr.status.state.value == "running"
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert any("erase_flash" in call for call in runner.calls)
    assert any("write_flash" in call for call in runner.calls)
    assert mgr.history()[0]["state"] == "success"

    # Verify manifest-driven offsets are used
    write_call = [c for c in runner.calls if "write_flash" in c][0]
    assert "0x10000" in write_call
    assert "0x1000" in write_call
    assert "0x8000" in write_call
    assert any("firmware.bin" in arg for arg in write_call)


@pytest.mark.asyncio
async def test_flash_uses_baseline_when_no_current(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=False, with_baseline=True)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    logs = mgr.logs_since(after=0)["lines"]
    assert any("baseline" in line for line in logs)


@pytest.mark.asyncio
async def test_flash_fails_fast_when_no_firmware_available(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path)
    mgr = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert "No firmware bundle available" in str(mgr.status.error)
    logs = mgr.logs_since(after=0)["lines"]
    assert any("updater" in line.lower() for line in logs)


@pytest.mark.asyncio
async def test_single_job_lock_and_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr = EspFlashManager(
        runner=_FakeRunner(hang=True),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    with pytest.raises(RuntimeError, match="already in progress"):
        mgr.start(port="/dev/ttyUSB0", auto_detect=False)
    assert mgr.cancel() is True
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "cancelled"


@pytest.mark.asyncio
async def test_multiple_ports_without_choice_fails_actionably(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    mgr = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts(
            [
                SerialPortInfo(port="/dev/ttyUSB0", description="USB A"),
                SerialPortInfo(port="/dev/ttyUSB1", description="USB B"),
            ]
        ),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert "Multiple serial ports" in str(mgr.status.error)


def _route_endpoint(router, path: str, method: str):
    for route in router.routes:
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route not found: {path} [{method}]")


@pytest.mark.asyncio
async def test_esp_flash_api_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    manager = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    state = type("S", (), {"esp_flash_manager": manager})()
    router = create_router(state)
    start_ep = _route_endpoint(router, "/api/settings/esp-flash/start", "POST")
    status_ep = _route_endpoint(router, "/api/settings/esp-flash/status", "GET")
    logs_ep = _route_endpoint(router, "/api/settings/esp-flash/logs", "GET")
    cancel_ep = _route_endpoint(router, "/api/settings/esp-flash/cancel", "POST")
    history_ep = _route_endpoint(router, "/api/settings/esp-flash/history", "GET")

    await start_ep(type("Req", (), {"port": None, "auto_detect": True})())
    assert manager._task is not None
    await manager._task
    status = await status_ep()
    assert status["state"] == "success"
    logs = await logs_ep(after=0)
    assert logs["next_index"] >= 1
    cancelled = await cancel_ep()
    assert cancelled == {"cancelled": False}
    history = await history_ep()
    assert len(history["attempts"]) == 1


@pytest.mark.asyncio
async def test_esp_flash_api_rejects_concurrent_start(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    manager = EspFlashManager(
        runner=_FakeRunner(hang=True),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    state = type("S", (), {"esp_flash_manager": manager})()
    router = create_router(state)
    start_ep = _route_endpoint(router, "/api/settings/esp-flash/start", "POST")

    await start_ep(type("Req", (), {"port": None, "auto_detect": True})())
    with pytest.raises(HTTPException) as exc_info:
        await start_ep(type("Req", (), {"port": None, "auto_detect": True})())
    assert exc_info.value.status_code == 409
    manager.cancel()
    assert manager._task is not None
    await manager._task


@pytest.mark.asyncio
async def test_flash_uses_python_module_fallback_when_esptool_binary_missing(
    tmp_path, monkeypatch
) -> None:
    def _which(name: str) -> str | None:
        return None

    monkeypatch.setattr("shutil.which", _which)
    monkeypatch.setattr(
        "importlib.util.find_spec",
        lambda name: SimpleNamespace() if name == "esptool" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert any(call[1:3] == ["-m", "esptool"] for call in runner.calls)


@pytest.mark.asyncio
async def test_flash_no_platformio_dependency(tmp_path, monkeypatch) -> None:
    """The Pi runtime path must not invoke PlatformIO for firmware."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"

    # Assert no PlatformIO was invoked (check command names, not full arg strings)
    for call in runner.calls:
        cmd_name = Path(call[0]).name.lower() if call else ""
        assert cmd_name not in ("pio", "platformio"), f"PlatformIO invoked: {call}"
        if len(call) > 2:
            assert call[1:3] != ["-m", "platformio"], f"PlatformIO module invoked: {call}"


@pytest.mark.asyncio
async def test_flash_fails_when_esptool_erase_step_fails(tmp_path, monkeypatch) -> None:
    def _which(name: str) -> str | None:
        return "/usr/bin/esptool.py" if name == "esptool.py" else None

    monkeypatch.setattr("shutil.which", _which)
    cache_dir = _make_cache(tmp_path, with_current=True)

    runner = _FakeRunner(fail_erase=True)
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert mgr.status.error == "Flash erase step failed"
    assert any("erase_flash" in " ".join(call) for call in runner.calls)
    assert not any("write_flash" in " ".join(call) for call in runner.calls)


@pytest.mark.asyncio
async def test_flash_no_network_access_in_flash_path(tmp_path, monkeypatch) -> None:
    """Flashing must not make any network requests."""
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    cache_dir = _make_cache(tmp_path, with_current=True)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        firmware_cache=FirmwareCache(FirmwareCacheConfig(cache_dir=str(cache_dir))),
    )

    # Monkeypatch urlopen to fail if called (patch at urllib level for resilience)
    def _block_network(*args, **kwargs):
        raise AssertionError("Network access during flashing is not allowed")

    monkeypatch.setattr("urllib.request.urlopen", _block_network)

    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
