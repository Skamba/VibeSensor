from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager

from vibesensor.updates.models import UpdatePhase
from vibesensor.updates.runner import UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.transport.failures import UpdateTransportStepError
from vibesensor.updates.wifi.wifi_config import UpdateWifiConfig

_UNESCAPED_COLON_RE = re.compile(r"(?<!\\):")
_PASSWD_FILE_DIR = "/dev/shm"


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


def psk_passwd_file(password: str) -> str:
    """Return nmcli ``passwd-file`` contents that supply *password* as the Wi-Fi PSK.

    nmcli unescapes backslashes in the value and strips unescaped leading and
    trailing whitespace, so backslashes, whitespace and control characters are
    written as octal escapes.
    """

    escaped = "".join(
        f"\\{ord(char):03o}" if char == "\\" or ord(char) <= 0x20 or ord(char) == 0x7F else char
        for char in password
    )
    return f"802-11-wireless-security.psk:{escaped}\n"


@contextmanager
def in_memory_passwd_file(password: str) -> Iterator[str]:
    """Yield a path from which root's nmcli reads *password* as a ``passwd-file``.

    The password must stay off command lines, which any local user can read in
    /proc/<pid>/cmdline, and off the SD card. It goes into an unnamed 0600 file
    in RAM (``O_TMPFILE`` on the /dev/shm tmpfs) that exists only as a
    descriptor of this process; the path is that descriptor under /proc, which
    only this user and root can open. Older root-side helpers already allow
    ``nmcli connection up ... passwd-file <path>``, so this needs no new root
    command.
    """

    fd = os.open(_PASSWD_FILE_DIR, os.O_TMPFILE | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        os.write(fd, psk_passwd_file(password).encode())
        yield f"/proc/{os.getpid()}/fd/{fd}"
    finally:
        os.close(fd)


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
        await self._configure_uplink_connection(secured=bool(password))

    async def bring_uplink_up(self, ssid: str, password: str) -> None:
        """Bring the prepared uplink connection up, retrying on scan lag.

        nmcli reads a password from a ``passwd-file``; NetworkManager then
        stores it in the root-only uplink profile.
        """

        if not password:
            await self._connect_with_retries(ssid, [])
            return
        with in_memory_passwd_file(password) as passwd_file:
            await self._connect_with_retries(ssid, ["passwd-file", passwd_file])

    async def _connect_with_retries(self, ssid: str, extra_args: list[str]) -> None:
        detail = ""
        max_attempts = max(1, self._config.uplink_connect_retries)
        for attempt_number in range(1, max_attempts + 1):
            if attempt_number > 1:
                await asyncio.sleep(self._config.uplink_rescan_delay_s)
            connect_result = await self._commands.run(
                [
                    "nmcli",
                    "--wait",
                    str(self._config.uplink_connect_wait_s),
                    "connection",
                    "up",
                    self._config.uplink_connection_name,
                    *extra_args,
                ],
                phase="connecting_wifi",
                timeout=float(self._config.uplink_connect_wait_s + 10),
                privileged=True,
            )
            if connect_result.returncode == 0:
                return
            detail = connect_result.stderr or ""
            if "No network with SSID" not in detail:
                break
            if attempt_number < max_attempts:
                self._status.log(
                    "SSID "
                    f"'{ssid}' not found on connect attempt {attempt_number}; "
                    "rescanning and retrying",
                )
                await self._rescan_wifi_networks()
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
            privileged=True,
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
            privileged=True,
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
            privileged=True,
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
                privileged=True,
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
            privileged=True,
        )
        if create_result.returncode == 0:
            return
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Failed to create uplink connection",
            detail=create_result.stderr,
        )

    async def _configure_uplink_connection(self, *, secured: bool) -> None:
        """Apply the non-secret updater settings to the uplink profile."""

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
                *(["wifi-sec.key-mgmt", "wpa-psk"] if secured else []),
            ],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            privileged=True,
        )
        if configure_result.returncode == 0:
            return
        await self._delete_uplink_connection()
        raise UpdateTransportStepError(
            phase=UpdatePhase.connecting_wifi,
            message="Failed to configure uplink",
            detail=configure_result.stderr,
        )

    async def _delete_uplink_connection(self) -> None:
        """Delete the transient uplink profile after a partial setup failure."""

        await self._commands.run(
            ["nmcli", "connection", "delete", self._config.uplink_connection_name],
            phase="connecting_wifi",
            timeout=self._config.nmcli_timeout_s,
            privileged=True,
        )
