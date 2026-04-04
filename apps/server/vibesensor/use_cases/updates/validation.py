"""Runtime prerequisite validation for OTA updates."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from vibesensor.shared.exceptions import UpdatePreparationError
from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.runner import (
    UpdateCommandExecutor,
    build_privilege_probe_args,
)
from vibesensor.use_cases.updates.status import UpdateStatusTracker

MIN_FREE_DISK_BYTES = 200 * 1024 * 1024


def _fail_validation(
    status: UpdateStatusTracker,
    message: str,
    detail: str = "",
) -> UpdatePreparationError:
    status.fail("validating", message, detail)
    return UpdatePreparationError(message)


def _probe_rollback_dir(rollback_dir: Path) -> None:
    """Verify that the rollback directory exists and accepts a small temp file."""

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


def _disk_check_path(rollback_dir: Path) -> Path:
    """Choose the filesystem whose free space should gate update work."""

    disk_check_path = rollback_dir.parent
    if not disk_check_path.exists():
        return Path("/var/lib") if Path("/var/lib").exists() else Path("/")
    return disk_check_path


async def validate_prerequisites(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    config: UpdateValidationConfig,
    request: UpdateRequest,
) -> None:
    """Validate tool availability, privilege access, and disk space."""
    if request.transport == UpdateTransport.wifi:
        status.log(f"Starting update with SSID: {request.ssid}")
    else:
        status.log("Starting update using existing USB internet")
    for tool in ("nmcli", "python3"):
        if not shutil.which(tool):
            raise _fail_validation(status, f"Required tool not found: {tool}")

    if os.geteuid() != 0:
        result = await commands.run(
            build_privilege_probe_args(),
            phase="validating",
            timeout=5,
            sudo=True,
        )
        if result.returncode != 0:
            raise _fail_validation(
                status,
                "Insufficient privileges",
                (
                    "Cannot run updater privileged commands non-interactively. "
                    "In dev/Docker environments, hotspot management is not available."
                ),
            )

    try:
        _probe_rollback_dir(config.rollback_dir)
    except OSError as exc:
        raise _fail_validation(
            status,
            "Rollback directory is not writable",
            f"{config.rollback_dir}: {exc}",
        ) from exc

    try:
        disk_check_path = _disk_check_path(config.rollback_dir)
        free_bytes = shutil.disk_usage(disk_check_path).free
        if free_bytes < config.min_free_disk_bytes:
            free_mb = free_bytes // (1024 * 1024)
            min_mb = config.min_free_disk_bytes // (1024 * 1024)
            raise _fail_validation(
                status,
                f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
            )
    except OSError as exc:
        raise _fail_validation(
            status,
            "Could not verify free disk space",
            str(exc),
        ) from exc
