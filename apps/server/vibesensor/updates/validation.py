"""Runtime prerequisite validation for OTA updates."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from vibesensor.common.exceptions import UpdatePreparationError
from vibesensor.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.updates.privilege import build_privilege_probe_args
from vibesensor.updates.runner import UpdateCommandExecutor
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_slots import VenvSlots

MIN_FREE_DISK_BYTES = 600 * 1024 * 1024
"""Room for one more venv slot (the pruned previous slot is not counted)."""


def _fail_validation(
    message: str,
    detail: str = "",
) -> UpdatePreparationError:
    return UpdatePreparationError(message, phase="validating", detail=detail)


def _disk_check_path(venv_root: Path) -> Path:
    """Return the nearest existing directory on the venv's filesystem."""

    for candidate in (venv_root, *venv_root.parents):
        if candidate.exists():
            return candidate
    return Path("/")


async def validate_prerequisites(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    config: UpdateValidationConfig,
    request: UpdateRequest,
) -> None:
    """Validate tool availability, privilege access, slot state, and disk space."""
    if request.transport == UpdateTransport.wifi:
        status.log(f"Starting update with SSID: {request.ssid}")
    else:
        status.log("Starting update using existing USB internet")
    for tool in ("nmcli", "python3"):
        if not shutil.which(tool):
            raise _fail_validation(f"Required tool not found: {tool}")

    if os.geteuid() != 0:
        result = await commands.run(
            build_privilege_probe_args(),
            phase="validating",
            timeout=5,
            sudo=True,
        )
        if result.returncode != 0:
            raise _fail_validation(
                "Insufficient privileges",
                (
                    "Cannot run updater privileged commands non-interactively. "
                    "In dev/Docker environments, hotspot management is not available."
                ),
            )

    slots = VenvSlots(config.venv_root)
    pending = slots.pending_boot()
    if pending is not None and pending.candidate == slots.active_slot():
        raise _fail_validation(
            "The previous update is still being verified",
            f"Version {pending.candidate} is in its boot check; try again in a minute",
        )

    try:
        disk_check_path = _disk_check_path(config.venv_root)
        free_bytes = shutil.disk_usage(disk_check_path).free
        if free_bytes < config.min_free_disk_bytes:
            free_mb = free_bytes // (1024 * 1024)
            min_mb = config.min_free_disk_bytes // (1024 * 1024)
            raise _fail_validation(
                f"Insufficient disk space: {free_mb} MiB free, {min_mb} MiB required",
            )
    except OSError as exc:
        raise _fail_validation(
            "Could not verify free disk space",
            str(exc),
        ) from exc
