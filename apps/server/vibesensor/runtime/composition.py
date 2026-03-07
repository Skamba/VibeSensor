"""Runtime composition helpers.

This module owns subsystem construction so the runtime coordinator remains a
thin holder of already-wired boundaries rather than a hidden composition root.
"""

from __future__ import annotations

from ..config import AppConfig
from ._state import RuntimeState
from .dependencies import (
    RuntimeIngressServices,
    RuntimeOperationsServices,
    RuntimePlatformServices,
)
from .lifecycle import LifecycleManager
from .processing_loop import ProcessingLoop, ProcessingLoopState
from .ws_broadcast import WsBroadcastCache, WsBroadcastService


def build_runtime_state(
    *,
    config: AppConfig,
    ingress: RuntimeIngressServices,
    operations: RuntimeOperationsServices,
    platform: RuntimePlatformServices,
) -> RuntimeState:
    """Construct a fully wired ``RuntimeState`` from focused service groups."""
    loop_state = ProcessingLoopState()
    ws_cache = WsBroadcastCache()
    processing_loop = ProcessingLoop(
        state=loop_state,
        fft_update_hz=config.processing.fft_update_hz,
        sample_rate_hz=config.processing.sample_rate_hz,
        fft_n=config.processing.fft_n,
        ingress=ingress,
    )
    ws_broadcast = WsBroadcastService(
        cache=ws_cache,
        ui_push_hz=config.processing.ui_push_hz,
        ui_heavy_push_hz=config.processing.ui_heavy_push_hz,
        ingress=ingress,
        operations=operations,
    )
    lifecycle = LifecycleManager(
        config=config,
        ingress=ingress,
        operations=operations,
        platform=platform,
        processing_loop=processing_loop,
        ws_broadcast=ws_broadcast,
    )
    return RuntimeState(
        config=config,
        ingress=ingress,
        operations=operations,
        platform=platform,
        loop_state=loop_state,
        ws_cache=ws_cache,
        processing_loop=processing_loop,
        ws_broadcast=ws_broadcast,
        lifecycle=lifecycle,
    )
