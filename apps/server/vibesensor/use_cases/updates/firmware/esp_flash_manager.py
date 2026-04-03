"""ESP32 firmware flash orchestration."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import shutil
import sys
import time
from pathlib import Path

from vibesensor.shared.exceptions import UpdateError
from vibesensor.use_cases.updates.firmware.esp_flash_runner import SubprocessFlashCommandRunner
from vibesensor.use_cases.updates.firmware.esp_flash_types import (
    EspFlashHistoryEntry,
    EspFlashHistoryEntryDict,
    EspFlashState,
    EspFlashStatus,
    FlashCommandRunner,
    FlashLogResponse,
    SerialPortInfoDict,
    SerialPortProvider,
)
from vibesensor.use_cases.updates.firmware.esp_serial import (
    PyserialPortProvider,
    resolve_selected_port,
)
from vibesensor.use_cases.updates.firmware.firmware_bundle import validate_bundle
from vibesensor.use_cases.updates.firmware.firmware_cache import FirmwareCache

LOGGER = logging.getLogger(__name__)

_FLASH_HISTORY_LIMIT = 10
_FLASH_STEP_TIMEOUT_S = 90
_FLASH_LOG_MAX_LINES: int = 2000
_FLASH_LOG_TRIM_TO: int = 1000
# Retain a bounded flash log buffer while keeping enough recent context for polling.


def _esptool_base_cmd() -> list[str] | None:
    """Return the preferred esptool invocation, or ``None`` when unavailable."""

    esptool = shutil.which("esptool.py")
    if esptool:
        return [esptool]
    esptool = shutil.which("esptool")
    if esptool:
        return [esptool]
    if importlib.util.find_spec("esptool") is not None:
        return [sys.executable, "-m", "esptool"]
    return None


class EspFlashManager:
    """Manages ESP32 firmware flash jobs: detect ports, run esptool, track history."""

    def __init__(
        self,
        *,
        runner: FlashCommandRunner | None = None,
        port_provider: SerialPortProvider | None = None,
        firmware_cache: FirmwareCache | None = None,
        repo_path: str | None = None,
    ) -> None:
        self._runner = runner or SubprocessFlashCommandRunner()
        self._ports = port_provider or PyserialPortProvider()
        self._firmware_cache = firmware_cache or FirmwareCache()
        self._status = EspFlashStatus()
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()
        self._job_counter = 0
        self._logs: list[str] = []
        self._history: list[EspFlashHistoryEntry] = []

    @property
    def status(self) -> EspFlashStatus:
        return self._status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        """The background task for the currently running flash job, or None."""
        return self._task

    async def list_ports(self) -> list[SerialPortInfoDict]:
        """List currently detected serial ports in API-response form."""

        ports = await self._ports.list_ports()
        return [p.to_dict() for p in ports]

    def start(self, *, port: str | None, auto_detect: bool) -> int:
        """Start a new flash job and return its monotonically increasing job id."""

        if self._task is not None and not self._task.done():
            raise UpdateError("Flash already in progress", status="conflict")
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
        """Request cancellation for the active flash job, if one exists."""

        if self._task is None or self._task.done():
            return False
        self._cancel_event.set()
        return True

    def logs_since(self, after: int) -> FlashLogResponse:
        """Return the retained flash log lines strictly after the requested index."""

        start = max(0, after)
        return FlashLogResponse(
            from_index=start,
            next_index=len(self._logs),
            lines=self._logs[start:],
        )

    def history(self) -> list[EspFlashHistoryEntryDict]:
        """Return completed flash attempts newest-first for the HTTP API."""

        return [entry.to_dict() for entry in self._history]

    def _append_log(self, line: str) -> None:
        """Append one log line while enforcing the bounded in-memory log buffer."""

        self._logs.append(line)
        if len(self._logs) > _FLASH_LOG_MAX_LINES:
            del self._logs[:-_FLASH_LOG_TRIM_TO]
        self._status.log_count = len(self._logs)
        LOGGER.debug("esp flash [%d]: %s", self._status.log_count, line)

    async def _run_flash_step(
        self,
        phase: str,
        args: list[str],
        *,
        cwd: Path,
        timeout_s: float = _FLASH_STEP_TIMEOUT_S,
    ) -> int:
        """Run one esptool phase, streaming its output into the job log."""

        self._status.phase = phase
        self._append_log(f"$ {' '.join(args)}")
        rc = await self._runner.run(
            args,
            cwd=str(cwd),
            line_cb=self._append_log,
            cancel_event=self._cancel_event,
            timeout_s=timeout_s,
        )
        if rc != 0:
            self._append_log(f"Command exited with code {rc}")
        return rc

    def _check_cancelled(self) -> bool:
        """Return *True* and finalize if the cancel event is set."""
        if not self._cancel_event.is_set():
            return False
        self._status.exit_code = 130
        self._finalize(state=EspFlashState.cancelled, error="Flash cancelled by user")
        return True

    def _finalize(self, *, state: EspFlashState, error: str | None = None) -> None:
        """Store terminal job state and append a bounded history entry."""

        self._status.state = state
        self._status.error = error
        self._status.finished_at = time.time()
        # Align `phase` with terminal states so API consumers get a coherent picture
        # (e.g. phase="erasing" + state="cancelled" is confusing).
        if state == EspFlashState.cancelled:
            self._status.phase = "cancelled"
        elif state == EspFlashState.failed:
            self._status.phase = "failed"
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
            del self._history[_FLASH_HISTORY_LIMIT:]

    async def _run_flash_job(self) -> None:
        esptool_cmd = _esptool_base_cmd()
        if esptool_cmd is None:
            self._status.exit_code = 127
            self._append_log("esptool not found. Install esptool to flash firmware.")
            self._finalize(state=EspFlashState.failed, error="esptool is not installed")
            return

        bundle_dir = self._firmware_cache.active_bundle_dir()
        if bundle_dir is None:
            self._status.exit_code = 1
            self._append_log(
                "No valid firmware bundle found in cache. "
                "Run the updater while online (vibesensor-fw-refresh) "
                "or reinstall Pi image with embedded baseline.",
            )
            self._finalize(
                state=EspFlashState.failed,
                error="No firmware bundle available (run updater while online)",
            )
            return

        try:
            self._status.phase = "preparing"
            meta = self._firmware_cache.active_meta()
            if meta is None:
                LOGGER.warning("Firmware bundle at %s has no metadata", bundle_dir)
            source_label = meta.source if meta else "unknown"
            tag_label = meta.tag if meta else "unknown"
            self._append_log(
                f"Using {source_label} firmware bundle (tag={tag_label}) from {bundle_dir}",
            )
            manifest = validate_bundle(bundle_dir)
            env = manifest.environments[0]
            self._append_log(f"Flashing environment: {env.name}")
            flash_args: list[str] = []
            for seg in env.segments:
                seg_path = bundle_dir / seg.file
                flash_args.extend([seg.offset, str(seg_path)])

            if not flash_args:
                self._status.exit_code = 1
                self._finalize(
                    state=EspFlashState.failed,
                    error="Firmware manifest has no segments to flash",
                )
                return

            try:
                selected_port = resolve_selected_port(
                    self._status.selected_port,
                    await self._ports.list_ports(),
                )
            except ValueError as exc:
                self._status.exit_code = 2
                self._append_log(str(exc))
                self._finalize(state=EspFlashState.failed, error=str(exc))
                return

            self._status.selected_port = selected_port
            port_prefix = [
                *esptool_cmd,
                "--chip",
                "esp32",
                "--port",
                selected_port,
                "--before",
                "default_reset",
                "--after",
                "hard_reset",
            ]

            erase_cmd = [*port_prefix, "erase_flash"]
            erase_rc = await self._run_flash_step(
                "erasing",
                erase_cmd,
                cwd=bundle_dir,
                timeout_s=45,
            )
            if self._check_cancelled():
                return
            if erase_rc != 0:
                self._status.exit_code = erase_rc
                self._finalize(state=EspFlashState.failed, error="Flash erase step failed")
                return

            write_cmd = [
                *port_prefix,
                "--baud",
                "115200",
                "write_flash",
                "-z",
                *flash_args,
            ]
            write_rc = await self._run_flash_step(
                "flashing",
                write_cmd,
                cwd=bundle_dir,
                timeout_s=120,
            )
            if self._check_cancelled():
                return
            self._status.exit_code = write_rc
            if write_rc != 0:
                self._finalize(state=EspFlashState.failed, error="Firmware flash failed")
                return
            self._status.phase = "done"
            self._finalize(state=EspFlashState.success)
        except asyncio.CancelledError:
            self._status.exit_code = 130
            self._finalize(
                state=EspFlashState.cancelled,
                error="Flash cancelled (server shutdown)",
            )
            raise
        except (OSError, ValueError) as exc:
            self._status.exit_code = 1
            self._append_log(str(exc))
            self._finalize(state=EspFlashState.failed, error=f"Flash failed: {exc}")
