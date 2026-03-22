from __future__ import annotations

import re

from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.wifi_config import UpdateWifiConfig

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
        candidate_ssid, security = parts[0].replace(r"\:", ":"), parts[1]
        if candidate_ssid.strip() != target:
            continue
        sec = security.strip()
        if sec and sec != "--":
            modes.add(sec)
    return modes


class UpdateUplinkProvisioner:
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

    async def prepare_uplink_connection(self, ssid: str, password: str) -> bool:
        if not password and not await self._validate_open_network(ssid):
            return False
        await self._delete_existing_uplink_connections()
        if not await self._create_uplink_connection(ssid):
            return False
        if not await self._configure_uplink_connection():
            return False
        if password and not await self._apply_wifi_password(password):
            return False
        return True

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
