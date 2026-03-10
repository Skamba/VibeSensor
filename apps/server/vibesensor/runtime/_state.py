"""RuntimeState – top-level runtime assembly over explicit subsystem owners."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from ..esp_flash_manager import EspFlashManager
from ..metrics_log import MetricsLogger
from ..update.manager import UpdateManager
from .lifecycle import LifecycleManager
from .subsystems import (
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeSettingsSubsystem,
    RuntimeWebsocketSubsystem,
)


@dataclass(slots=True)
class RuntimeState:
    """Top-level runtime that exposes explicit subsystem ownership."""

    config: AppConfig
    ingress: RuntimeIngressSubsystem
    settings: RuntimeSettingsSubsystem
    metrics_logger: MetricsLogger
    persistence: RuntimePersistenceSubsystem
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager
    processing: RuntimeProcessingSubsystem
    websocket: RuntimeWebsocketSubsystem
    lifecycle: LifecycleManager
