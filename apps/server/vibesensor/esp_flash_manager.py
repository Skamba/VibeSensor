from __future__ import annotations

import asyncio
import enum
import importlib.util
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_FLASH_HISTORY_LIMIT = 10


def _platformio_base_cmd() -> list[str] | None:
    pio = shutil.which("pio")
    if pio:
        return [pio]
    platformio = shutil.which("platformio")
    if platformio:
        return [platformio]
    if importlib.util.find_spec("platformio") is not None:
        return [sys.executable, "-m", "platformio"]
    return None


class EspFlashState(enum.StrEnum):
    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


@dataclass
class SerialPortInfo:
    port: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "description": self.description,
            "vid": self.vid,
            "pid": self.pid,
            "serial_number": self.serial_number,
        }


@dataclass
class EspFlashHistoryEntry:
    job_id: int
    state: EspFlashState
    selected_port: str | None
    auto_detect: bool
    started_at: float
    finished_at: float | None
    exit_code: int | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "state": self.state.value,
            "selected_port": self.selected_port,
            "auto_detect": self.auto_detect,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "error": self.error,
        }


@dataclass
class EspFlashStatus:
    state: EspFlashState = EspFlashState.idle
    phase: str = "idle"
    job_id: int | None = None
    selected_port: str | None = None
    auto_detect: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    exit_code: int | None = None
    error: str | None = None
    log_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "phase": self.phase,
            "job_id": self.job_id,
            "selected_port": self.selected_port,
            "auto_detect": self.auto_detect,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_success_at": self.last_success_at,
            "exit_code": self.exit_code,
            "error": self.error,
            "log_count": self.log_count,
        }


class SerialPortProvider:
    """Serial port discovery abstraction for testability."""

    async def list_ports(self) -> list[SerialPortInfo]:
        base_cmd = _platformio_base_cmd()
        if base_cmd is None:
            return []
        args = [*base_cmd, "device", "list", "--json-output"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _err = await proc.communicate()
        except FileNotFoundError:
            return []
        if (proc.returncode or 0) != 0:
            return []
        try:
            import json

            payload = json.loads(out.decode("utf-8", errors="replace"))
        except Exception:
            return []
        ports: list[SerialPortInfo] = []
        if not isinstance(payload, list):
            return ports
        for row in payload:
            if not isinstance(row, dict):
                continue
            port = str(row.get("port") or "").strip()
            if not port:
                continue
            ports.append(
                SerialPortInfo(
                    port=port,
                    description=str(row.get("description") or ""),
                    vid=row.get("vid") if isinstance(row.get("vid"), int) else None,
                    pid=row.get("pid") if isinstance(row.get("pid"), int) else None,
                    serial_number=str(row.get("serial_number") or "") or None,
                )
            )
        return ports


class FlashCommandRunner:
    """Process runner abstraction for streaming command output."""

    async def run(
        self,
        args: list[str],
        *,
        cwd: str,
        line_cb,
        cancel_event: asyncio.Event,
    ) -> int:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ},
        )
        assert proc.stdout is not None

        while proc.returncode is None:
            if cancel_event.is_set():
                proc.terminate()
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=0.25)
            except TimeoutError:
                continue
            if not line:
                await proc.wait()
                break
            line_cb(line.decode("utf-8", errors="replace").rstrip("\n"))
        await proc.wait()
        return proc.returncode or 0


class EspFlashManager:
    def __init__(
        self,
        *,
        runner: FlashCommandRunner | None = None,
        port_provider: SerialPortProvider | None = None,
        repo_path: str | None = None,
    ) -> None:
        self._runner = runner or FlashCommandRunner()
        self._ports = port_provider or SerialPortProvider()
        self._repo_path = Path(
            repo_path
            or os.environ.get("VIBESENSOR_REPO_PATH")
            or Path(__file__).resolve().parents[2]
        )
        self._firmware_dir = self._repo_path / "firmware" / "esp"
        self._status = EspFlashStatus()
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()
        self._job_counter = 0
        self._logs: list[str] = []
        self._history: list[EspFlashHistoryEntry] = []

    @property
    def status(self) -> EspFlashStatus:
        return self._status

    async def list_ports(self) -> list[dict[str, Any]]:
        ports = await self._ports.list_ports()
        return [p.to_dict() for p in ports]

    def start(self, *, port: str | None, auto_detect: bool) -> int:
        if self._task is not None and not self._task.done():
            raise RuntimeError("Flash already in progress")
        self._job_counter += 1
        self._logs = []
        self._cancel_event.clear()
        self._status = EspFlashStatus(
            state=EspFlashState.running,
            phase="validating",
            job_id=self._job_counter,
            selected_port=port.strip() if isinstance(port, str) and port.strip() else None,
            auto_detect=auto_detect,
            started_at=time.time(),
            last_success_at=self._status.last_success_at,
        )
        self._task = asyncio.get_running_loop().create_task(self._run_flash_job(), name="esp-flash")
        return self._job_counter

    def cancel(self) -> bool:
        if self._task is None or self._task.done():
            return False
        self._cancel_event.set()
        return True

    def logs_since(self, after: int) -> dict[str, Any]:
        start = max(0, after)
        return {"from_index": start, "next_index": len(self._logs), "lines": self._logs[start:]}

    def history(self) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self._history]

    def _append_log(self, line: str) -> None:
        self._logs.append(line)
        self._status.log_count = len(self._logs)
        LOGGER.debug("esp flash log line recorded")

    async def _resolve_port(self) -> str:
        configured = self._status.selected_port
        ports = await self._ports.list_ports()
        if configured:
            if any(p.port == configured for p in ports):
                return configured
            raise ValueError(
                f"Selected serial port {configured} not found. Check cable/permissions and retry."
            )
        if not ports:
            raise ValueError("No serial ports detected. Connect your ESP board and retry.")
        if len(ports) == 1:
            return ports[0].port
        usb_like = [p for p in ports if p.vid is not None or "usb" in p.description.lower()]
        if len(usb_like) == 1:
            return usb_like[0].port
        raise ValueError("Multiple serial ports detected. Select the ESP port explicitly.")

    async def _run_flash_step(self, phase: str, args: list[str]) -> int:
        self._status.phase = phase
        self._append_log(f"$ {' '.join(args)}")
        rc = await self._runner.run(
            args,
            cwd=str(self._firmware_dir),
            line_cb=self._append_log,
            cancel_event=self._cancel_event,
        )
        if rc != 0:
            self._append_log(f"Command exited with code {rc}")
        return rc

    def _finalize(self, *, state: EspFlashState, error: str | None = None) -> None:
        self._status.state = state
        self._status.error = error
        self._status.finished_at = time.time()
        if state == EspFlashState.success:
            self._status.last_success_at = self._status.finished_at
        self._history.insert(
            0,
            EspFlashHistoryEntry(
                job_id=int(self._status.job_id or 0),
                state=state,
                selected_port=self._status.selected_port,
                auto_detect=self._status.auto_detect,
                started_at=float(self._status.started_at or time.time()),
                finished_at=self._status.finished_at,
                exit_code=self._status.exit_code,
                error=error,
            ),
        )
        if len(self._history) > _FLASH_HISTORY_LIMIT:
            self._history = self._history[:_FLASH_HISTORY_LIMIT]

    async def _run_flash_job(self) -> None:
        pio_cmd = _platformio_base_cmd()
        if pio_cmd is None:
            self._status.exit_code = 127
            self._append_log("PlatformIO not found. Install platformio to flash firmware.")
            self._finalize(state=EspFlashState.failed, error="PlatformIO (pio) is not installed")
            return
        if not self._firmware_dir.is_dir():
            self._status.exit_code = 1
            self._finalize(
                state=EspFlashState.failed,
                error=f"Firmware directory missing: {self._firmware_dir}",
            )
            return

        try:
            selected_port = await self._resolve_port()
        except ValueError as exc:
            self._status.exit_code = 2
            self._append_log(str(exc))
            self._finalize(state=EspFlashState.failed, error=str(exc))
            return

        self._status.selected_port = selected_port
        base = [*pio_cmd, "run", "-d", str(self._firmware_dir)]
        port_args = ["--upload-port", selected_port]

        erase_rc = await self._run_flash_step("erasing", [*base, "-t", "erase", *port_args])
        if self._cancel_event.is_set():
            self._status.exit_code = 130
            self._finalize(state=EspFlashState.cancelled, error="Flash cancelled by user")
            return
        if erase_rc != 0:
            self._status.exit_code = erase_rc
            self._finalize(state=EspFlashState.failed, error="Flash erase step failed")
            return

        upload_rc = await self._run_flash_step("flashing", [*base, "-t", "upload", *port_args])
        if self._cancel_event.is_set():
            self._status.exit_code = 130
            self._finalize(state=EspFlashState.cancelled, error="Flash cancelled by user")
            return
        self._status.exit_code = upload_rc
        if upload_rc != 0:
            self._finalize(state=EspFlashState.failed, error="Firmware flash failed")
            return

        self._status.phase = "done"
        self._finalize(state=EspFlashState.success)
