"""Typed configuration schema dataclasses for the deployment-specific YAML settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vibesensor.app.config_paths import REPO_DIR

__all__ = [
    "APConfig",
    "AppConfig",
    "GPSConfig",
    "LoggingConfig",
    "RecordingConfig",
    "ServerConfig",
    "UDPConfig",
]


@dataclass(slots=True)
class APConfig:
    """Operator-owned Wi-Fi access-point settings (SSID and PSK).

    Interface, connection name, address, and channel are fixed in
    ``vibesensor.hotspot.constants``.
    """

    ssid: str
    psk: str


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
    """UDP data and control socket bind configuration."""

    data_host: str
    data_port: int
    control_host: str
    control_port: int

    def __post_init__(self) -> None:
        for name in ("data_port", "control_port"):
            val = getattr(self, name)
            if not isinstance(val, int) or not (1 <= val <= 65535):
                raise ValueError(f"UDPConfig.{name} must be 1–65535, got {val!r}")


@dataclass(slots=True)
class LoggingConfig:
    """Writable runtime file locations (history DB and application log)."""

    history_db_path: Path
    app_log_path: Path | None


@dataclass(slots=True)
class GPSConfig:
    """GPS enable flag; gpsd address is fixed in ``vibesensor.speed.gps_speed``."""

    gps_enabled: bool


@dataclass(slots=True)
class RecordingConfig:
    """Recording auto-stop cap (30 minutes outside isolated test runtimes)."""

    max_duration_s: float


@dataclass(slots=True)
class AppConfig:
    """Full application configuration assembled from the YAML config file."""

    ap: APConfig
    server: ServerConfig
    udp: UDPConfig
    logging: LoggingConfig
    gps: GPSConfig
    recording: RecordingConfig
    config_path: Path
    repo_dir: Path = REPO_DIR
