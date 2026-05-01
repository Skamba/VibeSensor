"""Transport-focused updater runtime assembly."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_verification import RollbackDeploymentVerifier
from vibesensor.use_cases.updates.runner import CommandRunner, UpdateCommandExecutor
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
)
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.transport.lifecycles import UpdateTransportLifecycles
from vibesensor.use_cases.updates.transport.usb_internet import UpdateUsbInternetSession
from vibesensor.use_cases.updates.usb_status import (
    UsbInternetStatusReader,
    UsbInternetStatusService,
)
from vibesensor.use_cases.updates.wifi.wifi_session import UpdateWifiSession

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.wifi.wifi_config import UpdateWifiConfig

__all__ = ["UpdateTransportRuntime", "build_update_transport_runtime"]


@dataclass(frozen=True, slots=True)
class UpdateTransportRuntime:
    coordinator: UpdateTransportCoordinator
    startup_recovery: UpdateStartupRecoveryCoordinator
    usb_status_service: UsbInternetStatusReader


def build_update_transport_runtime(
    *,
    runner: CommandRunner,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    reporter: UpdateTerminalStateReporter,
    wifi_config: UpdateWifiConfig,
    usb_internet_service: UsbInternetStatusReader | None,
    logger: logging.Logger,
    rollback_snapshots: RollbackSnapshotStore | None = None,
    rollback_verifier: RollbackDeploymentVerifier | None = None,
) -> UpdateTransportRuntime:
    status_service = usb_internet_service or UsbInternetStatusService(runner=runner)
    coordinator = UpdateTransportCoordinator(
        lifecycles=_build_transport_lifecycles(
            commands=commands,
            status=status,
            wifi_config=wifi_config,
            status_service=status_service,
        ),
        logger=logger,
    )
    return UpdateTransportRuntime(
        coordinator=coordinator,
        startup_recovery=UpdateStartupRecoveryCoordinator(
            status=status,
            reporter=reporter,
            transport_coordinator=coordinator,
            rollback_snapshots=rollback_snapshots,
            rollback_verifier=rollback_verifier,
        ),
        usb_status_service=status_service,
    )


def _build_transport_lifecycles(
    *,
    commands: UpdateCommandExecutor,
    status: UpdateStatusTracker,
    wifi_config: UpdateWifiConfig,
    status_service: UsbInternetStatusReader,
) -> UpdateTransportLifecycles:
    return UpdateTransportLifecycles(
        wifi=UpdateWifiSession(
            commands=commands,
            status=status,
            config=wifi_config,
        ),
        usb_internet=UpdateUsbInternetSession(
            status_service=status_service,
            commands=commands,
            status=status,
            config=wifi_config,
        ),
    )
