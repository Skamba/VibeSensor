"""Wi-Fi and hotspot operations for updater runs."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from .commands import UpdateCommandExecutor
from .status import UpdateStatusTracker

_UNESCAPED_COLON_RE = re.compile(r"(?<!\\):")


def ssid_security_modes(scan_output: str, ssid: str) -> set[str]:
    modes: set[str] = set()
    target = ssid.strip()
    if not target:
        return modes
    for line in scan_output.splitlines():
        raw = line.strip()
        if not raw or ":" not in raw:
            continue
        parts = _UNESCAPED_COLON_RE.split(raw, maxsplit=1)
        if len(parts) != 2:
            continue
        candidate_ssid, security = parts[0].replace("\\:", ":"), parts[1]
        if candidate_ssid.strip() != target:
            continue
        sec = security.strip()
        if sec and sec != "--":
            modes.add(sec)
    return modes


@dataclass(frozen=True, slots=True)
class UpdateWifiConfig:
    ap_con_name: str
    wifi_ifname: str
    uplink_connection_name: str
    uplink_connect_wait_s: int
    uplink_connect_retries: int
    uplink_fallback_dns: str
    dns_ready_min_wait_s: float
    dns_retry_interval_s: float
    dns_probe_host: str
    nmcli_timeout_s: float
    hotspot_restore_retries: int
    hotspot_restore_delay_s: float


class UpdateWifiController:
    """Owns hotspot shutdown, uplink connection, DNS readiness, and restore."""

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

    async def stop_hotspot(self) -> bool:
        self._tracker.log("Stopping hotspot...")
        rc, _, _ = await self._commands.run(
            ["nmcli", "connection", "down", self._config.ap_con_name],
            phase="stopping_hotspot",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if rc != 0:
            self._tracker.log("Hotspot down returned non-zero; may already be inactive")
        return True

    async def cleanup_uplink(self) -> None:
        await self._commands.run(
            ["nmcli", "connection", "down", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="restore",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )

    async def restore_hotspot(self) -> bool:
        await self.cleanup_uplink()
        for attempt in range(1, self._config.hotspot_restore_retries + 1):
            rc, _, _ = await self._commands.run(
                ["nmcli", "connection", "up", self._config.ap_con_name],
                phase="restore",
                timeout=self._config.nmcli_timeout_s,
                sudo=True,
            )
            if rc == 0:
                self._tracker.log(f"Hotspot restored on attempt {attempt}")
                return True
            self._tracker.log(f"Hotspot restore attempt {attempt} failed (rc={rc})")
            if attempt < self._config.hotspot_restore_retries:
                await asyncio.sleep(self._config.hotspot_restore_delay_s)
        self._tracker.add_issue("restoring_hotspot", "Failed to restore hotspot after retries")
        return False

    async def connect_uplink(self, ssid: str, password: str) -> bool:
        self._tracker.log(f"Connecting to Wi-Fi network: {ssid}")
        if not password and not await self._validate_open_network(ssid):
            return False
        await self._delete_existing_uplink_connections()
        if not await self._create_uplink_connection(ssid):
            return False
        if not await self._configure_uplink_connection():
            return False
        if password and not await self._apply_wifi_password(password):
            return False
        if not await self._bring_uplink_up(ssid):
            return False
        fallback = self._config.uplink_fallback_dns
        self._tracker.log(
            f"Wi-Fi connected successfully (client DNS fallback={fallback})",
        )
        return await self._wait_for_dns_ready()

    async def _validate_open_network(self, ssid: str) -> bool:
        rc, stdout, _ = await self._commands.run(
            [
                "nmcli",
                "-t",
                "-f",
                "SSID,SECURITY",
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
        if rc != 0:
            return True
        security_modes = ssid_security_modes(stdout, ssid)
        if not security_modes:
            return True
        self._tracker.fail(
            "connecting_wifi",
            "Wi-Fi password required for secured network",
            f"SSID '{ssid}' advertises security: {', '.join(sorted(security_modes))}",
        )
        return False

    async def _delete_existing_uplink_connections(self) -> None:
        rc, stdout, _ = await self._commands.run(
            ["nmcli", "-t", "-f", "UUID,NAME", "connection", "show"],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if rc != 0:
            return
        for line in stdout.splitlines():
            if not line:
                continue
            uuid, _, name = line.partition(":")
            if name != self._config.uplink_connection_name or not uuid:
                continue
            await self._commands.run(
                ["nmcli", "connection", "delete", "uuid", uuid],
                phase="connecting_wifi",
                timeout=self._config.nmcli_timeout_s,
                sudo=True,
            )

    async def _create_uplink_connection(self, ssid: str) -> bool:
        rc, _, stderr = await self._commands.run(
            [
                "nmcli",
                "connection",
                "add",
                "type",
                "wifi",
                "ifname",
                self._config.wifi_ifname,
                "con-name",
                self._config.uplink_connection_name,
                "autoconnect",
                "no",
                "ssid",
                ssid,
            ],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if rc == 0:
            return True
        self._tracker.fail("connecting_wifi", "Failed to create uplink connection", stderr)
        return False

    async def _configure_uplink_connection(self) -> bool:
        rc, _, stderr = await self._commands.run(
            [
                "nmcli",
                "connection",
                "modify",
                self._config.uplink_connection_name,
                "autoconnect",
                "no",
                "ipv4.method",
                "auto",
                "ipv4.ignore-auto-dns",
                "yes",
                "ipv4.dns",
                self._config.uplink_fallback_dns,
                "ipv6.method",
                "ignore",
            ],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if rc == 0:
            return True
        self._tracker.fail("connecting_wifi", "Failed to configure uplink", stderr)
        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        return False

    async def _apply_wifi_password(self, password: str) -> bool:
        rc, _, stderr = await self._commands.run(
            [
                "nmcli",
                "connection",
                "modify",
                self._config.uplink_connection_name,
                "wifi-sec.key-mgmt",
                "wpa-psk",
                "wifi-sec.psk",
                password,
            ],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if rc == 0:
            return True
        self._tracker.fail("connecting_wifi", "Failed to set Wi-Fi credentials", stderr)
        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        return False

    async def _bring_uplink_up(self, ssid: str) -> bool:
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

    async def _wait_for_dns_ready(self) -> bool:
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
