from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdatePhase,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
)
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.failures import UpdateTransportStepError
from vibesensor.use_cases.updates.transport.uplink_readiness import UpdateUplinkReadiness
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig


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

    __slots__ = ("_readiness", "_status", "_status_service")
    transport = UpdateTransport.usb_internet

    def __init__(
        self,
        *,
        status_service: UsbInternetStatusReader,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        config: UpdateWifiConfig,
    ) -> None:
        self._status_service = status_service
        self._status = status
        self._readiness = UpdateUplinkReadiness(
            commands=commands,
            status=status,
            config=config,
        )

    async def prepare(self, _request: UpdateRequest) -> UpdateUsbInternetSession:
        self._status.transition(UpdatePhase.connecting_usb_internet)
        await self.ensure_uplink_ready()
        return self

    async def abort_preparation(self) -> None:
        """No-op: prepare only validates an already-present external uplink."""
        return None

    async def ensure_uplink_ready(self) -> None:
        decision = _classify_usb_internet(await self._status_service.snapshot(activate=True))
        if not decision.usable:
            raise UpdateTransportStepError(
                phase=UpdatePhase.connecting_usb_internet,
                message=str(decision.issue_message),
                detail=decision.detail,
            )
        self._status.set_uplink_interface(decision.interface_name)
        if decision.log_message is not None:
            self._status.log(decision.log_message)
        await self._readiness.wait_for_dns_ready(
            phase=UpdatePhase.connecting_usb_internet,
            readiness_subject="USB internet",
            failure_message="USB internet detected, but internet/DNS is not ready",
        )

    async def complete_success(self) -> None:
        """No-op: the USB transport does not own the reused uplink on success."""
        return None

    async def cleanup_after_update(self) -> None:
        """No-op: there is no transport-local USB state to tear down after updates."""
        return None

    async def recover_interrupted_update(self, _status: UpdateJobStatus) -> None:
        """No-op: interrupted USB updates have no session-owned setup to restore."""
        return None
