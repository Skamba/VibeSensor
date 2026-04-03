from __future__ import annotations

import asyncio
import time

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig


class UpdateWifiReadiness:
    """Wait for the transient uplink connection to become usable for updates."""

    __slots__ = ("_commands", "_config", "_status_controller", "_status_recorder")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        config: UpdateWifiConfig,
    ) -> None:
        self._commands = commands
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._config = config

    async def bring_uplink_up(self, ssid: str) -> bool:
        """Bring the prepared uplink connection up, retrying on scan lag."""

        rc = 1
        stderr = ""
        for attempt in range(1, self._config.uplink_connect_retries + 1):
            rc, _, stderr = await self._commands.run(
                [
                    "nmcli",
                    "--wait",
                    str(self._config.uplink_connect_wait_s),
                    "connection",
                    "up",
                    self._config.uplink_connection_name,
                ],
                phase="connecting_wifi",
                timeout=float(self._config.uplink_connect_wait_s + 10),
                sudo=True,
            )
            if rc == 0:
                return True
            if "No network with SSID" not in (stderr or ""):
                break
            self._status_recorder.log(
                f"SSID '{ssid}' not found on connect attempt {attempt}; rescanning and retrying",
            )
            await self._commands.run(
                [
                    "nmcli",
                    "-t",
                    "-f",
                    "SSID,SIGNAL,CHAN,FREQ",
                    "dev",
                    "wifi",
                    "list",
                    "ifname",
                    self._config.wifi_ifname,
                    "--rescan",
                    "yes",
                ],
                phase="connecting_wifi",
                timeout=self._config.nmcli_timeout_s,
                sudo=True,
            )
            await asyncio.sleep(2.0)
        self._status_recorder.add_issue(
            "connecting_wifi",
            f"Failed to connect to Wi-Fi '{ssid}'",
            stderr,
        )
        self._status_controller.mark_failed()
        return False

    async def wait_for_dns_ready(
        self,
        *,
        phase: UpdatePhase | str = UpdatePhase.connecting_wifi,
        readiness_subject: str = "uplink",
        failure_message: str = "Connected to Wi-Fi, but internet/DNS is not ready",
    ) -> bool:
        """Wait for DNS resolution to succeed before download work begins."""

        self._status_recorder.log(
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
            rc, stdout, stderr = await self._commands.run(
                probe_cmd,
                phase=str(phase),
                timeout=5,
                sudo=False,
            )
            if rc == 0:
                self._status_recorder.log(f"DNS probe succeeded on attempt {attempt}")
                return True
            last_error = (stderr or stdout or f"exit {rc}").strip()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(self._config.dns_retry_interval_s)
        self._status_recorder.add_issue(
            phase.value if isinstance(phase, UpdatePhase) else phase,
            failure_message,
            (
                "Waited at least "
                f"{int(self._config.dns_ready_min_wait_s)} seconds for DNS resolution "
                f"({self._config.dns_probe_host}) before starting the updater. "
                f"Last probe error: {last_error or 'unknown'}"
            ),
        )
        self._status_controller.mark_failed()
        return False
