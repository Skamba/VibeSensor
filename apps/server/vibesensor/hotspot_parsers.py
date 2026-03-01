"""Text-parsing helpers and small utility types for hotspot self-heal diagnostics.

These functions operate on raw string output from system commands
and have no dependencies on runner/subprocess infrastructure.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path


def parse_active_connection_names(stdout: str) -> list[str]:
    """Parse ``nmcli -t -f NAME connection show`` output into a list of names."""
    rows = []
    for line in stdout.splitlines():
        line = line.strip()
        if line:
            rows.append(line)
    return rows


def parse_active_conn_device(con_name: str, stdout: str) -> tuple[bool, str | None]:
    """Parse ``nmcli -t -f NAME,DEVICE connection show --active`` to find *con_name*."""
    for row in stdout.splitlines():
        parts = [piece.strip() for piece in row.split(":", maxsplit=1)]
        if len(parts) != 2:
            continue
        name, device = parts
        if name == con_name:
            return True, device if device else None
    return False, None


def parse_ip(ip_show_output: str) -> str | None:
    """Extract the first ``inet`` CIDR from ``ip -4 addr show`` output."""
    for line in ip_show_output.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            fields = line.split()
            if len(fields) >= 2:
                return fields[1]
    return None


def expected_ip_match(expected_cidr: str, actual_cidr: str | None) -> bool:
    """Return True if the IP part of both CIDR strings is the same."""
    if actual_cidr is None:
        return False
    expected_ip = expected_cidr.split("/", maxsplit=1)[0]
    actual_ip = actual_cidr.split("/", maxsplit=1)[0]
    return expected_ip == actual_ip


def parse_iw_info(iw_output: str) -> tuple[bool, str | None]:
    """Parse ``iw dev <ifname> info`` for AP mode and channel."""
    ap_mode = False
    channel = None
    channel_re = re.compile(r"channel\s+(\d+)")
    for line in iw_output.splitlines():
        text = line.strip().lower()
        if text.startswith("type ") and " ap" in f" {text}":
            ap_mode = True
        match = channel_re.search(text)
        if match:
            channel = match.group(1)
    return ap_mode, channel


def parse_rfkill_blocked(output: str) -> bool:
    """Return True if rfkill reports any block."""
    lowered = output.lower()
    return "soft blocked: yes" in lowered or "hard blocked: yes" in lowered


def nm_log_signals(log_excerpt: str) -> tuple[str | None, str | None]:
    """Extract diagnostic signals from NetworkManager journal output."""
    lower = log_excerpt.lower()
    if "no address range available" in lower:
        return "dhcp_no_range", None
    if "failed to start" in lower and "dnsmasq" in lower:
        return "dhcp_dnsmasq_start_failed", None
    if "address already in use" in lower and (":53" in lower or "port 53" in lower):
        return "port53_conflict", None
    return None, None


def parse_port53_conflict(ss_stdout: str) -> str | None:
    """Parse ``ss -ltnup sport = :53`` to find non-NM processes on port 53."""
    lines = [line.strip() for line in ss_stdout.splitlines() if line.strip()]
    conflict_names: list[str] = []
    for line in lines:
        lowered = line.lower()
        if "dnsmasq" in lowered and "networkmanager" in lowered:
            continue
        if "users:(" in lowered:
            # Real ss output uses double-parens: users:(("name",pid=…))
            # Older or alternative formats may use single-paren: users:("name",…)
            for delimiter in ('users:(("', 'users:("'):
                parts = line.split(delimiter, maxsplit=1)
                if len(parts) == 2:
                    proc = parts[1].split('"', maxsplit=1)[0]
                    conflict_names.append(proc)
                    break
    if not conflict_names:
        return None
    return ",".join(sorted(set(conflict_names)))


class HealStateStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> dict[str, float]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}
            return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}
        except Exception:
            logging.getLogger(__name__).debug(
                "HealStateStore: ignoring corrupt state file %s", self._path, exc_info=True
            )
            return {}

    def _save(self, data: dict[str, float]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    def allow(self, key: str, min_interval_s: int) -> bool:
        data = self._load()
        now = time.time()
        last = data.get(key, 0.0)
        if now - last < max(0, min_interval_s):
            return False
        data[key] = now
        self._save(data)
        return True
