from __future__ import annotations

import asyncio
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


def _seed_artifacts(repo: Path) -> None:
    artifact_dir = repo / "firmware" / "esp" / ".pio" / "build" / "m5stack_atom"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
        (artifact_dir / name).write_bytes(b"bin")


def _make_repo(tmp_path: Path, *, with_artifacts: bool = True) -> Path:
    repo = tmp_path / "repo"
    (repo / "firmware" / "esp").mkdir(parents=True)
    if with_artifacts:
        _seed_artifacts(repo)
    return repo


def _make_repo_with_apps_hint(tmp_path: Path) -> tuple[Path, Path]:
    repo = _make_repo(tmp_path)
    apps_hint = repo / "apps"
    (apps_hint / "server").mkdir(parents=True)
    return repo, apps_hint


@pytest.mark.asyncio
async def test_port_discovery_returns_metadata(tmp_path) -> None:
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
        repo_path=str(_make_repo(tmp_path)),
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
async def test_flash_job_runs_erase_and_upload_and_records_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(_make_repo(tmp_path)),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr.status.state.value == "running"
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert any("erase_flash" in call for call in runner.calls)
    assert any("write_flash" in call for call in runner.calls)
    assert mgr.history()[0]["state"] == "success"


@pytest.mark.asyncio
async def test_single_job_lock_and_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    mgr = EspFlashManager(
        runner=_FakeRunner(hang=True),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(_make_repo(tmp_path)),
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
    mgr = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts(
            [
                SerialPortInfo(port="/dev/ttyUSB0", description="USB A"),
                SerialPortInfo(port="/dev/ttyUSB1", description="USB B"),
            ]
        ),
        repo_path=str(_make_repo(tmp_path)),
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
    manager = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(_make_repo(tmp_path)),
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
    manager = EspFlashManager(
        runner=_FakeRunner(hang=True),
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(_make_repo(tmp_path)),
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
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(_make_repo(tmp_path)),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    first = runner.calls[0]
    assert Path(first[0]).name.startswith("python")
    assert first[1:3] == ["-m", "esptool"]


@pytest.mark.asyncio
async def test_flash_finds_firmware_dir_when_repo_hint_points_to_apps(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    repo, apps_hint = _make_repo_with_apps_hint(tmp_path)
    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(apps_hint),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "success"
    assert any(
        str(repo / "firmware" / "esp" / ".pio" / "build" / "m5stack_atom" / "firmware.bin") in call
        for call in runner.calls
    )


@pytest.mark.asyncio
async def test_flash_fails_when_prebuilt_artifacts_are_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/esptool.py" if name == "esptool.py" else None,
    )
    repo = _make_repo(tmp_path, with_artifacts=False)

    runner = _FakeRunner()
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(repo),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert "Missing prebuilt firmware artifacts" in str(mgr.status.error)


@pytest.mark.asyncio
async def test_flash_fails_when_esptool_erase_step_fails(tmp_path, monkeypatch) -> None:
    def _which(name: str) -> str | None:
        return "/usr/bin/esptool.py" if name == "esptool.py" else None

    monkeypatch.setattr("shutil.which", _which)
    repo = _make_repo(tmp_path)

    runner = _FakeRunner(fail_erase=True)
    mgr = EspFlashManager(
        runner=runner,
        port_provider=_FakePorts([SerialPortInfo(port="/dev/ttyUSB0", description="USB UART")]),
        repo_path=str(repo),
    )
    mgr.start(port=None, auto_detect=True)
    assert mgr._task is not None
    await mgr._task
    assert mgr.status.state.value == "failed"
    assert mgr.status.error == "Flash erase step failed"
    assert any("erase_flash" in " ".join(call) for call in runner.calls)
    assert not any("write_flash" in " ".join(call) for call in runner.calls)
