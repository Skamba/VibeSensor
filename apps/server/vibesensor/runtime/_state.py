"""RuntimeState – top-level runtime assembly over explicit subsystem owners."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from .lifecycle import LifecycleManager
from .subsystems import (
    RuntimeDiagnosticsSubsystem,
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRouteServices,
    RuntimeSettingsSubsystem,
    RuntimeUpdateSubsystem,
    RuntimeWebsocketSubsystem,
)


@dataclass(slots=True)
class RuntimeState:
    """Top-level runtime that exposes explicit subsystem ownership."""

    config: AppConfig
    ingress: RuntimeIngressSubsystem
    settings: RuntimeSettingsSubsystem
    diagnostics: RuntimeDiagnosticsSubsystem
    persistence: RuntimePersistenceSubsystem
    updates: RuntimeUpdateSubsystem
    processing: RuntimeProcessingSubsystem
    websocket: RuntimeWebsocketSubsystem
    routes: RuntimeRouteServices
    lifecycle: LifecycleManager
