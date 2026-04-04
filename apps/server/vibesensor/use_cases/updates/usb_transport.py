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
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_failures import UpdateTransportStepError
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

    __slots__ = ("_readiness", "_status_controller", "_status_recorder", "_status_service")
    transport = UpdateTransport.usb_internet

    def __init__(
        self,
        *,
        status_service: UsbInternetStatusReader,
        commands: UpdateCommandExecutor,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        config: UpdateWifiConfig,
    ) -> None:
        self._status_service = status_service
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._readiness = UpdateWifiReadiness(
            commands=commands,
            status_recorder=status_recorder,
            config=config,
        )

    async def prepare(self, request: UpdateRequest) -> None:
        del request
        self._status_controller.transition(UpdatePhase.connecting_usb_internet)
        try:
            await self.ensure_uplink_ready()
        except UpdateTransportStepError as exc:
            self._status_recorder.add_issue(exc.phase, str(exc), exc.detail)
            self._status_controller.mark_failed()
            raise UpdateTransportError(
                "Failed to prepare the USB internet uplink for update"
            ) from exc

    async def abort_preparation(self) -> None:
        return None

    async def ensure_uplink_ready(self) -> None:
        decision = _classify_usb_internet(await self._status_service.snapshot(activate=True))
        if not decision.usable:
            raise UpdateTransportStepError(
                phase=UpdatePhase.connecting_usb_internet,
                message=str(decision.issue_message),
                detail=decision.detail,
            )
        self._status_controller.set_uplink_interface(decision.interface_name)
        if decision.log_message is not None:
            self._status_recorder.log(decision.log_message)
        await self._readiness.wait_for_dns_ready(
            phase=UpdatePhase.connecting_usb_internet,
            readiness_subject="USB internet",
            failure_message="USB internet detected, but internet/DNS is not ready",
        )

    async def complete_success(self, message: str) -> None:
        self._status_controller.mark_success()
        self._status_recorder.log(message)
        self._status_controller.persist()

    async def cleanup_after_update(self) -> None:
        return None

    async def recover_interrupted_update(self) -> None:
        return None
