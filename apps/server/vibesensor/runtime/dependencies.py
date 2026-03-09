"""Focused runtime service groups.

These dataclasses define the explicit ownership boundaries used by runtime
composition. They replace the previous pattern where ``RuntimeState`` directly
stored every concrete service and subsystem builders reached through that large
shared bag.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..analysis_settings import AnalysisSettingsStore
from ..esp_flash_manager import EspFlashManager
from ..gps_speed import GPSSpeedMonitor
from ..history_db import HistoryDB
from ..metrics_log import MetricsLogger
from ..processing import SignalProcessor
from ..registry import ClientRegistry
from ..settings_store import SettingsStore
from ..udp_control_tx import UDPControlPlane
from ..update.manager import UpdateManager
from ..worker_pool import WorkerPool
from ..ws_hub import WebSocketHub


@dataclass(slots=True)
class RuntimeIngressServices:
    """Services that own ingest, processing, and control-plane traffic."""

    registry: ClientRegistry
    processor: SignalProcessor
    control_plane: UDPControlPlane


@dataclass(slots=True)
class RuntimeOperationsServices:
    """Settings, GPS, and metrics services used during runtime."""

    settings_store: SettingsStore
    analysis_settings: AnalysisSettingsStore
    gps_monitor: GPSSpeedMonitor
    metrics_logger: MetricsLogger


@dataclass(slots=True)
class RuntimePlatformServices:
    """Long-lived platform resources with explicit startup/shutdown ownership."""

    ws_hub: WebSocketHub
    history_db: HistoryDB
    update_manager: UpdateManager
    esp_flash_manager: EspFlashManager
    worker_pool: WorkerPool
