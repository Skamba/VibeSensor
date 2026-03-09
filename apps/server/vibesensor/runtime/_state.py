"""RuntimeState – top-level runtime assembly over explicit subsystem owners."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AppConfig
from .lifecycle import LifecycleManager
from .subsystems import (
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRecordingSubsystem,
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
    recording: RuntimeRecordingSubsystem
    persistence: RuntimePersistenceSubsystem
    updates: RuntimeUpdateSubsystem
    processing: RuntimeProcessingSubsystem
    websocket: RuntimeWebsocketSubsystem
    routes: RuntimeRouteServices
    lifecycle: LifecycleManager
