from __future__ import annotations

from vibesensor.shared.exceptions import UpdateTransportError
from vibesensor.use_cases.updates.models import UpdatePhase, UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader
from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig
from vibesensor.use_cases.updates.wifi.wifi_readiness import UpdateWifiReadiness


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
        status = await self._status_service.snapshot(activate=True)
        if not status.detected:
            self._tracker.fail(
                UpdatePhase.connecting_usb_internet,
                "USB internet not detected",
                status.diagnostic,
            )
            return False
        if not status.usable:
            self._tracker.fail(
                UpdatePhase.connecting_usb_internet,
                "USB internet detected but not usable",
                status.diagnostic,
            )
            return False
        self._tracker.set_uplink_interface(status.interface_name)
        if status.connection_name:
            self._tracker.log(
                f"Using existing USB internet connection '{status.connection_name}' on "
                f"{status.interface_name}",
            )
        else:
            self._tracker.log(f"Using existing USB internet on {status.interface_name}")
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
