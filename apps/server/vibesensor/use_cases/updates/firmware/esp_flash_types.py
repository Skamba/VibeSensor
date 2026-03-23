"""ESP flash state, API payload shapes, and service protocols."""

from __future__ import annotations

import asyncio
import enum
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict

__all__ = [
    "EspFlashHistoryEntry",
    "EspFlashHistoryEntryDict",
    "EspFlashState",
    "EspFlashStatus",
    "EspFlashStatusDict",
    "FlashCommandRunner",
    "FlashLogResponse",
    "SerialPortInfo",
    "SerialPortInfoDict",
    "SerialPortProvider",
]


class EspFlashState(enum.StrEnum):
    """State machine values for an ESP32 flash job."""

    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"
    cancelled = "cancelled"


class SerialPortInfoDict(TypedDict):
    """Serialised shape of :class:`SerialPortInfo` for API responses."""

    port: str
    description: str
    vid: int | None
    pid: int | None
    serial_number: str | None


class EspFlashHistoryEntryDict(TypedDict):
    """Serialised shape of :class:`EspFlashHistoryEntry` for API responses."""

    job_id: int
    state: str
    selected_port: str | None
    auto_detect: bool
    started_at: float
    finished_at: float | None
    exit_code: int | None
    error: str | None


class EspFlashStatusDict(TypedDict):
    """Serialised shape of :class:`EspFlashStatus` for API responses."""

    state: str
    phase: str
    job_id: int | None
    selected_port: str | None
    auto_detect: bool
    started_at: float | None
    finished_at: float | None
    last_success_at: float | None
    exit_code: int | None
    error: str | None
    log_count: int


class FlashLogResponse(TypedDict):
    """Response shape for the flash log polling endpoint."""

    from_index: int
    next_index: int
    lines: list[str]


@dataclass
class SerialPortInfo:
    """Metadata about a detected serial port (USB device)."""

    port: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None

    def to_dict(self) -> SerialPortInfoDict:
        """Serialise serial port info to a plain dict for API responses."""
        return SerialPortInfoDict(
            port=self.port,
            description=self.description,
            vid=self.vid,
            pid=self.pid,
            serial_number=self.serial_number,
        )


@dataclass
class EspFlashHistoryEntry:
    """Record of a completed or cancelled ESP32 flash job."""

    job_id: int
    state: EspFlashState
    selected_port: str | None
    auto_detect: bool
    started_at: float
    finished_at: float | None
    exit_code: int | None
    error: str | None

    def to_dict(self) -> EspFlashHistoryEntryDict:
        """Serialise flash history entry to a plain dict for API responses."""
        return EspFlashHistoryEntryDict(
            job_id=self.job_id,
            state=self.state.value,
            selected_port=self.selected_port,
            auto_detect=self.auto_detect,
            started_at=self.started_at,
            finished_at=self.finished_at,
            exit_code=self.exit_code,
            error=self.error,
        )


@dataclass
class EspFlashStatus:
    """Current real-time status of the ESP32 flash manager."""

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

    def to_dict(self) -> EspFlashStatusDict:
        return EspFlashStatusDict(
            state=self.state.value,
            phase=self.phase,
            job_id=self.job_id,
            selected_port=self.selected_port,
            auto_detect=self.auto_detect,
            started_at=self.started_at,
            finished_at=self.finished_at,
            last_success_at=self.last_success_at,
            exit_code=self.exit_code,
            error=self.error,
            log_count=self.log_count,
        )


class SerialPortProvider(Protocol):
    """Serial port discovery abstraction for testability."""

    async def list_ports(self) -> list[SerialPortInfo]: ...


class FlashCommandRunner(Protocol):
    """Process runner abstraction for streaming command output."""

    async def run(
        self,
        args: list[str],
        *,
        cwd: str,
        line_cb: Callable[[str], None],
        cancel_event: asyncio.Event,
        timeout_s: float | None = None,
    ) -> int: ...
