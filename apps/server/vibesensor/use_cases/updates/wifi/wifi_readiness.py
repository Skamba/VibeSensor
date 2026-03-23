from __future__ import annotations

import asyncio
import time

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig


class UpdateWifiReadiness:
    __slots__ = ("_commands", "_config", "_tracker")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._commands = commands
        self._tracker = tracker
        self._config = config

    async def bring_uplink_up(self, ssid: str) -> bool:
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
            self._tracker.log(
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
        self._tracker.fail(
            "connecting_wifi",
            f"Failed to connect to Wi-Fi '{ssid}'",
            stderr,
        )
        return False

    async def wait_for_dns_ready(self) -> bool:
        self._tracker.log(
            "Validating uplink internet/DNS readiness for at least "
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
                phase="connecting_wifi",
                timeout=5,
                sudo=False,
            )
            if rc == 0:
                self._tracker.log(f"DNS probe succeeded on attempt {attempt}")
                return True
            last_error = (stderr or stdout or f"exit {rc}").strip()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(self._config.dns_retry_interval_s)
        self._tracker.fail(
            "connecting_wifi",
            "Connected to Wi-Fi, but internet/DNS is not ready",
            (
                "Waited at least "
                f"{int(self._config.dns_ready_min_wait_s)} seconds for DNS resolution "
                f"({self._config.dns_probe_host}) before starting the updater. "
                f"Last probe error: {last_error or 'unknown'}"
            ),
        )
        return False
