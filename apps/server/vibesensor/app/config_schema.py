"""Typed configuration schema dataclasses and validation constants."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from vibesensor.shared.constants.type_checks import NUMERIC_TYPES

from .config_paths import REPO_DIR

__all__ = [
    "VALID_24GHZ_CHANNELS",
    "APConfig",
    "APSelfHealConfig",
    "AppConfig",
    "GPSConfig",
    "LoggingConfig",
    "ProcessingConfig",
    "ServerConfig",
    "TracingConfig",
    "UDPConfig",
    "UpdateConfig",
]

LOGGER = logging.getLogger("vibesensor.app.settings")

_PROCESSING_POS_FIELDS: tuple[str, ...] = (
    "sample_rate_hz",
    "waveform_seconds",
    "client_live_ttl_seconds",
    "client_ttl_seconds",
)
_PROCESSING_POS_MIN: int = 1
_MAX_BUFFER_SAMPLES: int = 524_288

VALID_24GHZ_CHANNELS: frozenset[int] = frozenset(range(1, 15))


@dataclass(slots=True)
class APSelfHealConfig:
    """Configuration for the Wi-Fi AP self-heal watchdog."""

    enabled: bool
    diagnostics_lookback_minutes: int
    min_restart_interval_seconds: int
    state_file: Path

    def __post_init__(self) -> None:
        val = self.diagnostics_lookback_minutes
        if not isinstance(val, int) or val < 1:
            raise ValueError(
                "ap.self_heal.diagnostics_lookback_minutes must be"
                f" a positive integer, got {val!r}",
            )
        mri = self.min_restart_interval_seconds
        if not isinstance(mri, int) or mri < 0:
            raise ValueError(
                "ap.self_heal.min_restart_interval_seconds must be a non-negative integer,"
                f" got {mri!r}",
            )


@dataclass(slots=True)
class APConfig:
    """Wi-Fi access-point configuration (SSID, PSK, IP, channel, NM connection)."""

    ssid: str
    psk: str
    ip: str
    channel: int
    ifname: str
    con_name: str
    self_heal: APSelfHealConfig


@dataclass(slots=True)
class ServerConfig:
    """HTTP server bind host and port configuration."""

    host: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ValueError(f"ServerConfig.port must be 1–65535, got {self.port!r}")


@dataclass(slots=True)
class UDPConfig:
    """UDP data and control socket configuration (hosts, ports, queue size)."""

    data_host: str
    data_port: int
    control_host: str
    control_port: int
    data_queue_maxsize: int

    def __post_init__(self) -> None:
        for name in ("data_port", "control_port"):
            val = getattr(self, name)
            if not isinstance(val, int) or not (1 <= val <= 65535):
                raise ValueError(f"UDPConfig.{name} must be 1–65535, got {val!r}")
        if not isinstance(self.data_queue_maxsize, int) or self.data_queue_maxsize < 1:
            raise ValueError(
                f"UDPConfig.data_queue_maxsize must be ≥1, got {self.data_queue_maxsize!r}",
            )


@dataclass(slots=True)
class ProcessingConfig:
    """Signal processing parameters plus live-vs-retained client timing."""

    sample_rate_hz: int
    waveform_seconds: int
    client_live_ttl_seconds: int
    client_ttl_seconds: int
    accel_scale_g_per_lsb: float | None

    def __post_init__(self) -> None:
        for field_name in _PROCESSING_POS_FIELDS:
            val = getattr(self, field_name)
            if val < _PROCESSING_POS_MIN:
                LOGGER.warning(
                    "processing.%s=%s is below minimum %s — clamped to %s",
                    field_name,
                    val,
                    _PROCESSING_POS_MIN,
                    _PROCESSING_POS_MIN,
                )
                object.__setattr__(self, field_name, _PROCESSING_POS_MIN)

        buffer_samples = self.sample_rate_hz * self.waveform_seconds
        if buffer_samples > _MAX_BUFFER_SAMPLES:
            clamped_seconds = max(1, _MAX_BUFFER_SAMPLES // self.sample_rate_hz)
            LOGGER.warning(
                "processing.sample_rate_hz=%s × waveform_seconds=%s = %s samples "
                "exceeds per-client buffer limit (%s) — clamping waveform_seconds to %s",
                self.sample_rate_hz,
                self.waveform_seconds,
                buffer_samples,
                _MAX_BUFFER_SAMPLES,
                clamped_seconds,
            )
            object.__setattr__(self, "waveform_seconds", clamped_seconds)

        if self.client_ttl_seconds < self.client_live_ttl_seconds:
            LOGGER.warning(
                "processing.client_ttl_seconds=%s is below "
                "processing.client_live_ttl_seconds=%s — clamping retention TTL to %s",
                self.client_ttl_seconds,
                self.client_live_ttl_seconds,
                self.client_live_ttl_seconds,
            )
            object.__setattr__(self, "client_ttl_seconds", self.client_live_ttl_seconds)


@dataclass(slots=True)
class LoggingConfig:
    """Run-logging configuration (file path, sample rate, history DB, timeouts)."""

    metrics_log_hz: int
    no_data_timeout_s: float
    history_db_path: Path
    persist_history_db: bool
    run_retention_days: int
    shutdown_analysis_timeout_s: float
    app_log_path: Path | None

    def __post_init__(self) -> None:
        if not isinstance(self.metrics_log_hz, int) or self.metrics_log_hz < 1:
            clamped = max(1, int(self.metrics_log_hz or 1))
            LOGGER.warning(
                "logging.metrics_log_hz=%r is invalid — clamped to %s",
                self.metrics_log_hz,
                clamped,
            )
            object.__setattr__(self, "metrics_log_hz", clamped)
        if not isinstance(self.no_data_timeout_s, NUMERIC_TYPES) or self.no_data_timeout_s < 0:
            LOGGER.warning(
                "logging.no_data_timeout_s=%r is invalid — clamped to 15.0",
                self.no_data_timeout_s,
            )
            object.__setattr__(self, "no_data_timeout_s", 15.0)
        if not isinstance(self.run_retention_days, int) or self.run_retention_days < 1:
            clamped = max(1, int(self.run_retention_days or 7))
            LOGGER.warning(
                "logging.run_retention_days=%r is invalid — clamped to %s",
                self.run_retention_days,
                clamped,
            )
            object.__setattr__(self, "run_retention_days", clamped)
        if (
            not isinstance(self.shutdown_analysis_timeout_s, NUMERIC_TYPES)
            or self.shutdown_analysis_timeout_s < 0
        ):
            LOGGER.warning(
                "logging.shutdown_analysis_timeout_s=%r is invalid — clamped to 30.0",
                self.shutdown_analysis_timeout_s,
            )
            object.__setattr__(self, "shutdown_analysis_timeout_s", 30.0)


@dataclass(slots=True)
class GPSConfig:
    """GPS device configuration (enable/disable flag, gpsd host/port)."""

    gps_enabled: bool
    gpsd_host: str
    gpsd_port: int

    def __post_init__(self) -> None:
        if not isinstance(self.gpsd_port, int) or not (1 <= self.gpsd_port <= 65535):
            raise ValueError(f"gps.gpsd_port must be 1–65535, got {self.gpsd_port!r}")


@dataclass(slots=True)
class UpdateConfig:
    """Server auto-update configuration (rollback directory)."""

    rollback_dir: Path


@dataclass(slots=True)
class TracingConfig:
    """Backend tracing configuration (optional JSONL export)."""

    enabled: bool
    output_path: Path


@dataclass(slots=True)
class AppConfig:
    """Full application configuration assembled from the YAML config file."""

    ap: APConfig
    server: ServerConfig
    udp: UDPConfig
    processing: ProcessingConfig
    logging: LoggingConfig
    gps: GPSConfig
    update: UpdateConfig
    tracing: TracingConfig
    config_path: Path
    repo_dir: Path = REPO_DIR
