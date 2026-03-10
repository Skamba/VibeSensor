"""Runtime composition helpers.

This module wires already-built subsystems into the top-level runtime without
re-expanding them into another broad facade.
"""

from __future__ import annotations

from ..config import AppConfig
from ._state import RuntimeState
from .builders import build_lifecycle_manager
from .lifecycle import LifecycleManager
from .subsystems import (
    RuntimeIngressSubsystem,
    RuntimePersistenceSubsystem,
    RuntimeProcessingSubsystem,
    RuntimeRecordingSubsystem,
    RuntimeSettingsSubsystem,
    RuntimeUpdateSubsystem,
    RuntimeWebsocketSubsystem,
)


def build_runtime_state(
    *,
    config: AppConfig,
    ingress: RuntimeIngressSubsystem,
    settings: RuntimeSettingsSubsystem,
    recording: RuntimeRecordingSubsystem,
    persistence: RuntimePersistenceSubsystem,
    updates: RuntimeUpdateSubsystem,
    processing: RuntimeProcessingSubsystem,
    websocket: RuntimeWebsocketSubsystem,
) -> RuntimeState:
    """Construct a fully wired ``RuntimeState`` from explicit subsystems."""
    lifecycle: LifecycleManager = build_lifecycle_manager(
        config=config,
        ingress=ingress,
        settings=settings,
        recording=recording,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
    )
    return RuntimeState(
        config=config,
        ingress=ingress,
        settings=settings,
        recording=recording,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
        lifecycle=lifecycle,
    )
