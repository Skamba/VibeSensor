from __future__ import annotations

import asyncio
from pathlib import Path

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
    def __init__(self, *, hang: bool = False, fail_upload: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.hang = hang
        self.fail_upload = fail_upload

    async def run(
        self,
        args: list[str],
        *,
        cwd: str,
        line_cb,
        cancel_event: asyncio.Event,
    ) -> int:
        self.calls.append(list(args))
        line_cb(f"running {' '.join(args)}")
        if self.hang:
            while not cancel_event.is_set():
                await asyncio.sleep(0.05)
            return 130
        if self.fail_upload and "-t" in args and "upload" in args:
            return 1
        return 0


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "firmware" / "esp").mkdir(parents=True)
    return repo


@pytest.mark.asyncio
async def test_port_discovery_returns_metadata(tmp_path) -> None:
    mgr = EspFlashManager(
        runner=_FakeRunner(),
        port_provider=_FakePorts(
            [SerialPortInfo(port="/dev/ttyUSB0", description="USB UART", vid=6790, pid=29987, serial_number="abc")]
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
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pio")
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
    assert any("-t" in call and "erase" in call for call in runner.calls)
    assert any("-t" in call and "upload" in call for call in runner.calls)
    assert mgr.history()[0]["state"] == "success"


@pytest.mark.asyncio
async def test_single_job_lock_and_cancel(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pio")
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
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pio")
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
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pio")
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
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/pio")
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
