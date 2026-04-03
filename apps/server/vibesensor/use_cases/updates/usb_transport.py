from __future__ import annotations

from dataclasses import dataclass

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import (
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_readiness import UpdateWifiReadiness


@dataclass(frozen=True, slots=True)
class UsbInternetReadinessDecision:
    """Interpret one USB internet snapshot before control-side readiness waits."""

    usable: bool
    issue_message: str | None = None
    log_message: str | None = None
    interface_name: str | None = None
    detail: str = ""


def _classify_usb_internet(status: UsbInternetStatus) -> UsbInternetReadinessDecision:
    if not status.detected:
        return UsbInternetReadinessDecision(
            usable=False,
            issue_message="USB internet not detected",
            detail=status.diagnostic,
        )
    if not status.usable:
        return UsbInternetReadinessDecision(
            usable=False,
            issue_message="USB internet detected but not usable",
            detail=status.diagnostic,
        )
    interface_name = status.interface_name
    if status.connection_name:
        return UsbInternetReadinessDecision(
            usable=True,
            interface_name=interface_name,
            log_message=(
                f"Using existing USB internet connection '{status.connection_name}' on "
                f"{interface_name}"
            ),
        )
    return UsbInternetReadinessDecision(
        usable=True,
        interface_name=interface_name,
        log_message=f"Using existing USB internet on {interface_name}",
    )


class UpdateUsbInternetSession:
    """Validate and reuse an already-present USB internet uplink for updates."""

    __slots__ = ("_readiness", "_status_service", "_tracker")
    transport = UpdateTransport.usb_internet

    def __init__(
        self,
        *,
        status_service: UsbInternetStatusReader,
        commands: UpdateCommandExecutor,
        tracker: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._status_service = status_service
        self._tracker = tracker
        self._readiness = UpdateWifiReadiness(
            commands=commands,
            tracker=tracker,
            config=config,
        )

    async def prepare(self, request: UpdateRequest) -> None:
        del request
        self._tracker.transition(UpdatePhase.connecting_usb_internet)
        if not await self.ensure_uplink_ready():
            raise UpdateTransportError("Failed to prepare the USB internet uplink for update")

    async def abort_preparation(self) -> None:
        return None

    async def ensure_uplink_ready(self) -> bool:
        decision = _classify_usb_internet(await self._status_service.snapshot(activate=True))
        if not decision.usable:
            self._tracker.fail(
                UpdatePhase.connecting_usb_internet,
                str(decision.issue_message),
                decision.detail,
            )
            return False
        self._tracker.set_uplink_interface(decision.interface_name)
        if decision.log_message is not None:
            self._tracker.log(decision.log_message)
        return await self._readiness.wait_for_dns_ready(
            phase=UpdatePhase.connecting_usb_internet,
            readiness_subject="USB internet",
            failure_message="USB internet detected, but internet/DNS is not ready",
        )

    async def complete_success(self, message: str) -> None:
        self._tracker.mark_success(message)

    async def cleanup_after_update(self) -> None:
        return None

    async def recover_interrupted_update(self) -> None:
        return None
