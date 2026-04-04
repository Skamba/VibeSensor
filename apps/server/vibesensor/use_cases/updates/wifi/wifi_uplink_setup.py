from __future__ import annotations

import re

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.transport_failures import UpdateTransportStepError
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig

_UNESCAPED_COLON_RE = re.compile(r"(?<!\\):")


def ssid_security_modes(scan_output: str, ssid: str) -> set[str]:
    """Return the advertised security modes for the matching SSID in nmcli output."""

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
    """Create and configure the temporary Wi-Fi uplink connection for updates."""

    __slots__ = ("_commands", "_config")

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        config: UpdateWifiConfig,
    ) -> None:
        self._commands = commands
        self._config = config

    async def prepare_uplink_connection(self, ssid: str, password: str) -> None:
        """Create the transient uplink profile and apply any required credentials."""

        if not password:
            await self._validate_open_network(ssid)
        await self._delete_existing_uplink_connections()
        await self._create_uplink_connection(ssid)
        await self._configure_uplink_connection()
        if password:
            await self._apply_wifi_password(password)

    async def _validate_open_network(self, ssid: str) -> None:
        """Reject blank-password attempts when the scanned SSID is secured."""

        scan_result = await self._commands.run(
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
        if scan_result.returncode != 0:
            return
        security_modes = ssid_security_modes(scan_result.stdout, ssid)
        if not security_modes:
            return
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Wi-Fi password required for secured network",
            detail=f"SSID '{ssid}' advertises security: {', '.join(sorted(security_modes))}",
        )

    async def _delete_existing_uplink_connections(self) -> None:
        """Remove any stale transient uplink profiles before recreating them."""

        connection_list = await self._commands.run(
            ["nmcli", "-t", "-f", "UUID,NAME", "connection", "show"],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
        if connection_list.returncode != 0:
            return
        for line in connection_list.stdout.splitlines():
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

    async def _create_uplink_connection(self, ssid: str) -> None:
        """Create a new transient uplink profile for the requested SSID."""

        create_result = await self._commands.run(
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
        if create_result.returncode == 0:
            return
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Failed to create uplink connection",
            detail=create_result.stderr,
        )

    async def _configure_uplink_connection(self) -> None:
        """Apply the non-secret updater defaults to the uplink profile."""

        configure_result = await self._commands.run(
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
        if configure_result.returncode == 0:
            return
        await self._delete_uplink_connection()
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Failed to configure uplink",
            detail=configure_result.stderr,
        )

    async def _apply_wifi_password(self, password: str) -> None:
        """Apply WPA-PSK credentials to the transient uplink profile."""

        password_result = await self._commands.run(
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
        if password_result.returncode == 0:
            return
        await self._delete_uplink_connection()
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Failed to set Wi-Fi credentials",
            detail=password_result.stderr,
        )

    async def _delete_uplink_connection(self) -> None:
        """Delete the transient uplink profile after a partial setup failure."""

        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            sudo=True,
        )
