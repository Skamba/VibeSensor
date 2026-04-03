"""Observation helpers for configured Bluetooth OBD admin state."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.adapters.obd.admin_client import ObdAdminClient
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.shared.operational_errors import OperationalError

__all__ = ["ObdAdminObservation", "observe_configured_obd_device"]


@dataclass(frozen=True, slots=True)
class ObdAdminObservation:
    """Latest configured-device admin observation, separated from monitor mutation."""

    snapshot: ObdDeviceSnapshot | None
    helper_error: str | None


def observe_configured_obd_device(
    *,
    admin_client: ObdAdminClient,
    configured_mac: str | None,
) -> ObdAdminObservation:
    """Fetch admin/device state for the configured adapter without mutating monitor state."""

    if configured_mac is None:
        return ObdAdminObservation(snapshot=None, helper_error=None)
    try:
        snapshot = admin_client.device_info(configured_mac)
    except OperationalError as exc:
        return ObdAdminObservation(snapshot=None, helper_error=str(exc))
    return ObdAdminObservation(snapshot=snapshot, helper_error=None)
