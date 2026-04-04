from __future__ import annotations

from vibesensor.use_cases.updates.models import UsbInternetStatus

from .usb_status_inspection import UsbCandidateObservation

_USB_ACTIVATION_STATES = frozenset({"disconnected", "unavailable", "unknown"})

__all__ = [
    "candidate_diagnostic",
    "select_best_candidate",
    "should_attempt_activation",
    "status_from_candidate",
]


def _candidate_rank(candidate: UsbCandidateObservation) -> tuple[int, int, int]:
    return (
        2 if candidate.usable else 0,
        1 if candidate.state == "connected" else 0,
        1 if candidate.driver == "ipheth" else 0,
    )


def select_best_candidate(
    candidates: list[UsbCandidateObservation],
) -> UsbCandidateObservation:
    return max(candidates, key=_candidate_rank)


def candidate_diagnostic(candidate: UsbCandidateObservation) -> str:
    if candidate.nmcli_error:
        return f"Could not query NetworkManager device status ({candidate.nmcli_error})."
    if candidate.state != "connected":
        if candidate.carrier_on is False:
            return (
                f"USB interface '{candidate.interface_name}' is detected, but link carrier is off. "
                "Enable USB tethering/personal hotspot and trust this Pi on the phone."
            )
        return (
            f"USB interface '{candidate.interface_name}' is detected, but NetworkManager reports "
            f"state '{candidate.state or 'unknown'}'."
        )
    if candidate.addr_error:
        return (
            f"USB interface '{candidate.interface_name}' is connected, but IPv4 status "
            f"could not be read ({candidate.addr_error})."
        )
    if not candidate.ipv4_addresses:
        return (
            f"USB interface '{candidate.interface_name}' is connected, "
            "but no IPv4 address is assigned yet."
        )
    if candidate.route_error:
        return (
            f"USB interface '{candidate.interface_name}' is connected, but route status "
            f"could not be read ({candidate.route_error})."
        )
    if not candidate.has_default_route:
        return (
            f"USB interface '{candidate.interface_name}' is connected, "
            "but no default IPv4 route is active."
        )
    return f"USB internet is ready on '{candidate.interface_name}'."


def should_attempt_activation(candidate: UsbCandidateObservation) -> bool:
    return (
        not candidate.usable
        and candidate.state in _USB_ACTIVATION_STATES
        and candidate.carrier_on is not False
    )


def status_from_candidate(
    candidate: UsbCandidateObservation,
    *,
    diagnostic: str | None = None,
) -> UsbInternetStatus:
    return UsbInternetStatus(
        detected=True,
        usable=candidate.usable,
        interface_name=candidate.interface_name,
        connection_name=candidate.connection_name,
        driver=candidate.driver,
        ipv4_addresses=candidate.ipv4_addresses,
        gateway=candidate.gateway,
        has_default_route=candidate.has_default_route,
        diagnostic=diagnostic if diagnostic is not None else candidate_diagnostic(candidate),
    )
