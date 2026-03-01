"""Network helpers for the update subsystem (nmcli operations)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .models import UpdateIssue
from .runner import CommandRunner, _sudo_prefix, sanitize_log_line

LOGGER = logging.getLogger(__name__)

UPLINK_CONNECTION_NAME = "VibeSensor-Uplink"
UPLINK_CONNECT_WAIT_S = 30
UPLINK_FALLBACK_DNS = "1.1.1.1,1.0.0.1"
DNS_READY_MIN_WAIT_S = 10.0
DNS_RETRY_INTERVAL_S = 1.0
DNS_PROBE_HOST = "api.github.com"
NMCLI_TIMEOUT_S = 30
HOTSPOT_RESTORE_RETRIES = 3
HOTSPOT_RESTORE_DELAY_S = 2


def parse_wifi_diagnostics(log_dir: str = "/var/log/wifi") -> list[UpdateIssue]:
    """Parse wifi diagnostic files into structured issues."""
    issues: list[UpdateIssue] = []
    log_path = Path(log_dir)
    if not log_path.is_dir():
        return issues

    summary = log_path / "summary.txt"
    if summary.is_file():
        try:
            text = summary.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("status=") and "FAILED" in line.upper():
                    issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot summary reports failure",
                            detail=line,
                        )
                    )
        except OSError:
            pass

    hotspot_log = log_path / "hotspot.log"
    if hotspot_log.is_file():
        try:
            text = hotspot_log.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for line in lines[-100:]:
                lower = line.lower()
                if "error" in lower or "failed" in lower or "timeout" in lower:
                    sanitized = sanitize_log_line(line)
                    issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot log issue",
                            detail=sanitized,
                        )
                    )
        except OSError:
            pass

    return issues


async def cleanup_uplink(runner: CommandRunner) -> None:
    """Best-effort removal of the temporary uplink connection."""
    sudo = _sudo_prefix()
    await runner.run(
        [*sudo, "nmcli", "connection", "down", UPLINK_CONNECTION_NAME],
        timeout=NMCLI_TIMEOUT_S,
    )
    await runner.run(
        [*sudo, "nmcli", "connection", "delete", UPLINK_CONNECTION_NAME],
        timeout=NMCLI_TIMEOUT_S,
    )


async def restore_hotspot(
    runner: CommandRunner,
    ap_con_name: str,
) -> bool:
    """Bring the AP connection back up with retries.  Returns True on success."""
    sudo = _sudo_prefix()
    # Clean up temporary uplink first
    await cleanup_uplink(runner)

    for attempt in range(1, HOTSPOT_RESTORE_RETRIES + 1):
        rc, _, _ = await runner.run(
            [*sudo, "nmcli", "connection", "up", ap_con_name],
            timeout=NMCLI_TIMEOUT_S,
        )
        if rc == 0:
            return True
        if attempt < HOTSPOT_RESTORE_RETRIES:
            await asyncio.sleep(HOTSPOT_RESTORE_DELAY_S)

    return False


async def wait_for_dns_ready(runner: CommandRunner) -> tuple[bool, str]:
    """Wait for uplink DNS resolution.  Returns (success, last_error)."""
    probe_cmd = [
        "python3",
        "-c",
        (f"import socket; socket.getaddrinfo('{DNS_PROBE_HOST}', 443, proto=socket.IPPROTO_TCP)"),
    ]
    deadline = time.monotonic() + DNS_READY_MIN_WAIT_S
    last_error = ""
    attempt = 0

    while True:
        attempt += 1
        rc, stdout, stderr = await runner.run(probe_cmd, timeout=5)
        if rc == 0:
            return True, ""
        last_error = (stderr or stdout or f"exit {rc}").strip()
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(DNS_RETRY_INTERVAL_S)

    return False, last_error
