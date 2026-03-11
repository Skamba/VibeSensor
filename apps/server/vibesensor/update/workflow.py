"""Top-level updater workflow orchestration and prerequisite validation."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .runner import UpdateCommandExecutor
from .status import UpdateStatusTracker

# ---------------------------------------------------------------------------
# Prerequisite validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UpdateValidationConfig:
    rollback_dir: Path
    min_free_disk_bytes: int


def _probe_rollback_dir(rollback_dir: Path) -> None:
    rollback_dir.mkdir(parents=True, exist_ok=True)
    probe_handle = tempfile.NamedTemporaryFile(
        prefix=".rollback-write-probe-",
        dir=rollback_dir,
        delete=False,
    )
    probe_path = Path(probe_handle.name)
    try:
        probe_handle.write(b"ok")
        probe_handle.flush()
    finally:
        probe_handle.close()
    probe_path.unlink(missing_ok=True)


async def validate_prerequisites(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    config: UpdateValidationConfig,
    ssid: str,
) -> bool:
    """Validate tool availability, privilege access, and disk space."""
    tracker.log(f"Starting update with SSID: {ssid}")
    for tool in ("nmcli", "python3"):
        if not shutil.which(tool):
            tracker.fail("validating", f"Required tool not found: {tool}")
            return False

    if os.geteuid() != 0:
        rc, _, _ = await commands.run(
            ["sudo", "-n", "true"],
            phase="validating",
            timeout=5,
            sudo=False,
        )
        if rc != 0:
            tracker.fail(
                "validating",
                "Insufficient privileges",
                "Cannot run sudo non-interactively. In dev/Docker "
                "environments, hotspot management is not available.",
            )
            return False

    try:
        _probe_rollback_dir(config.rollback_dir)
    except OSError as exc:
        tracker.fail(
            "validating",
            "Rollback directory is not writable",
            f"{config.rollback_dir}: {exc}",
        )
        return False

    try:
        disk_check_path = config.rollback_dir.parent
        if not disk_check_path.exists():
            disk_check_path = Path("/var/lib") if Path("/var/lib").exists() else Path("/")
        free_bytes = shutil.disk_usage(disk_check_path).free
        if free_bytes < config.min_free_disk_bytes:
            free_mb = free_bytes // (1024 * 1024)
            min_mb = config.min_free_disk_bytes // (1024 * 1024)
            tracker.fail(
                "validating",
                f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
            )
            return False
    except OSError as exc:
        tracker.fail(
            "validating",
            "Could not verify free disk space",
            str(exc),
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Service control
# ---------------------------------------------------------------------------


async def schedule_service_restart(
    *,
    commands: UpdateCommandExecutor,
    tracker: UpdateStatusTracker,
    service_name: str,
    restart_unit: str,
) -> bool:
    """Schedule a systemd restart of the backend service."""
    restart_attempts = [
        [
            "systemd-run",
            "--unit",
            restart_unit,
            "--on-active=2s",
            "systemctl",
            "restart",
            service_name,
        ],
        ["systemctl", "restart", service_name],
    ]
    for command in restart_attempts:
        rc, _, _ = await commands.run(
            command,
            phase="done",
            timeout=30,
            sudo=True,
        )
        if rc == 0:
            tracker.log("Scheduled backend service restart")
            return True
    return False
