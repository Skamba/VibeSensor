from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig

__all__ = ["UpdateUplinkReadiness"]


class UpdateUplinkReadiness:
    """Wait for an already-activated uplink to become internet/DNS ready."""

    __slots__ = ("_commands", "_config", "_status")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._commands = commands
        self._status = status
        self._config = config

    async def wait_for_dns_ready(
        self,
        *,
        phase: UpdatePhase | str = UpdatePhase.connecting_wifi,
        readiness_subject: str = "uplink",
        failure_message: str = "Connected to Wi-Fi, but internet/DNS is not ready",
    ) -> None:
        """Wait for DNS resolution to succeed before download work begins."""

        self._status.log(
            f"Validating {readiness_subject} internet/DNS readiness for at least "
            f"{int(self._config.dns_ready_min_wait_s)}s...",
        )
        deadline = time.monotonic() + self._config.dns_ready_min_wait_s
        last_error = ""
        attempt = 0
        probe_cmd = [
            "python3",
            "-c",
            (
                "import socket; "
                "socket.getaddrinfo("
                f"'{self._config.dns_probe_host}', 443, proto=socket.IPPROTO_TCP)"
            ),
        ]
        while True:
            attempt += 1
            probe_result = await self._commands.run(
                probe_cmd,
                phase=str(phase),
                timeout=5,
                sudo=False,
            )
            if probe_result.returncode == 0:
                self._status.log(f"DNS probe succeeded on attempt {attempt}")
                return
            last_error = (
                probe_result.stderr or probe_result.stdout or f"exit {probe_result.returncode}"
            ).strip()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(self._config.dns_retry_interval_s)
        raise UpdateTransportStepError(
            phase=phase,
            message=failure_message,
            detail=(
                "Waited at least "
                f"{int(self._config.dns_ready_min_wait_s)} seconds for DNS resolution "
                f"({self._config.dns_probe_host}) before starting the updater. "
                f"Last probe error: {last_error or 'unknown'}"
            ),
        )
