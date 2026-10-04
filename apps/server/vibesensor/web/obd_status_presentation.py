"""HTTP-facing OBD status presentation helpers."""

from __future__ import annotations

from vibesensor.speed.obd.models import ObdStatusSnapshot

__all__ = ["obd_debug_hint"]

_HELPER_MISSING_HINT = (
    "Re-run apps/server/scripts/install_pi.sh on the Pi to install the privileged helper "
    "(vibesensor-privileged.socket) that Bluetooth scan and pairing need."
)


def obd_debug_hint(snapshot: ObdStatusSnapshot) -> str | None:
    """Return operator guidance from a pure OBD runtime snapshot."""

    helper_error = snapshot.helper_error
    if helper_error is not None:
        lowered = helper_error.lower()
        if "privileged helper" in lowered:
            return _HELPER_MISSING_HINT
        return "Bluetooth admin helper failed; try scan/pair again after power-cycling the adapter."

    last_error = snapshot.last_error
    if last_error is not None:
        lowered = last_error.lower()
        if "privileged helper" in lowered:
            return _HELPER_MISSING_HINT
    if snapshot.configured_device_mac is None:
        return (
            "Pair a Bluetooth OBD adapter in Settings before selecting OBD-II as the speed source."
        )
    if not snapshot.paired:
        return "Re-run Bluetooth pairing; the configured adapter is no longer paired with the Pi."
    if not snapshot.trusted:
        return "Trust the configured OBD adapter again so reconnects can succeed without prompts."
    if snapshot.rfcomm_channel is None:
        return "Rescan the adapter after power-cycling it; no RFCOMM serial channel was advertised."
    if snapshot.connection_state == "disconnected":
        return "Keep the adapter powered and in range; VibeSensor will keep retrying automatically."
    return None
