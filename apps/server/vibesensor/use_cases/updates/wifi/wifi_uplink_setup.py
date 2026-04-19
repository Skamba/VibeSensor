from __future__ import annotations

import asyncio
import re

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from vibesensor.use_cases.updates.models import UpdatePhase
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig

_UNESCAPED_COLON_RE = re.compile(r"(?<!\\):")
_UPLINK_RESCAN_DELAY_S = 2.0


class _RetryableSsidNotFoundError(Exception):
    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class _NonRetryableUplinkConnectError(Exception):
    __slots__ = ("detail",)

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


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

    async def prepare_uplink_connection(self, ssid: str, password: str) -> None:
        """Create the transient uplink profile and apply any required credentials."""

        if not password:
            await self._validate_open_network(ssid)
        await self._delete_existing_uplink_connections()
        await self._create_uplink_connection(ssid)
        await self._configure_uplink_connection()
        if password:
            await self._apply_wifi_password(password)

    async def bring_uplink_up(self, ssid: str) -> None:
        """Bring the prepared uplink connection up, retrying on scan lag."""

        detail = ""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._config.uplink_connect_retries),
                wait=wait_fixed(_UPLINK_RESCAN_DELAY_S),
                retry=retry_if_exception_type(_RetryableSsidNotFoundError),
                sleep=asyncio.sleep,
                reraise=True,
            ):
                with attempt:
                    connect_result = await self._commands.run(
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
                    if connect_result.returncode == 0:
                        return
                    detail = connect_result.stderr or ""
                    attempt_number = attempt.retry_state.attempt_number
                    if "No network with SSID" not in detail:
                        raise _NonRetryableUplinkConnectError(detail)
                    if attempt_number < self._config.uplink_connect_retries:
                        self._status.log(
                            "SSID "
                            f"'{ssid}' not found on connect attempt {attempt_number}; "
                            "rescanning and retrying",
                        )
                        await self._rescan_wifi_networks()
                    raise _RetryableSsidNotFoundError(detail)
        except _RetryableSsidNotFoundError as exc:
            detail = exc.detail
        except _NonRetryableUplinkConnectError as exc:
            detail = exc.detail
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message=f"Failed to connect to Wi-Fi '{ssid}'",
            detail=detail,
        )

    async def _rescan_wifi_networks(self) -> None:
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
