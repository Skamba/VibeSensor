"""Application configuration loading and validation.

Loads the YAML config file, deep-merges with defaults, and validates
all sections into typed ``AppConfig`` dataclass hierarchy.

Module structure
----------------
1. **Config dataclasses** — ``ServerConfig``, ``UDPConfig``,
   ``ProcessingConfig``, ``LoggingConfig``, ``GPSConfig``, ``APConfig``,
   ``APSelfHealConfig``, ``UpdateConfig``, ``AppConfig``.
2. **Defaults** — ``DEFAULT_CONFIG`` dict and ``documented_default_config()``.
3. **Loading** — ``load_config()`` reads YAML, deep-merges with defaults,
   and validates into the ``AppConfig`` hierarchy.
4. **Path resolution** — ``SERVER_DIR``, ``REPO_DIR`` for deployment paths.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from ._config_defaults import (
    DEFAULT_CONFIG,
    DEFAULT_UDP_CONTROL_PORT,
    DEFAULT_UDP_DATA_PORT,
    _require_config_section,
    documented_default_config,
)
from .constants import NUMERIC_TYPES
from .json_types import JsonObject, is_json_object
from .json_utils import deep_merge

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_UDP_CONTROL_PORT",
    "DEFAULT_UDP_DATA_PORT",
    "REPO_DIR",
    "SERVER_DIR",
    "VALID_24GHZ_CHANNELS",
    "APConfig",
    "APSelfHealConfig",
    "AppConfig",
    "GPSConfig",
    "LoggingConfig",
    "ProcessingConfig",
    "ServerConfig",
    "UDPConfig",
    "UpdateConfig",
    "documented_default_config",
    "load_config",
]

SERVER_DIR = Path(__file__).resolve().parents[1]
"""Root of the ``apps/server/`` package tree."""

REPO_DIR = SERVER_DIR.parents[1]
LOGGER = logging.getLogger(__name__)

# ProcessingConfig validation constants (hoisted to avoid per-instance allocation)
_PROCESSING_POS_FIELDS: tuple[str, ...] = (
    "sample_rate_hz",
    "waveform_seconds",
    "client_ttl_seconds",
)
_PROCESSING_POS_MIN: int = 1
_MAX_BUFFER_SAMPLES: int = 524_288

VALID_24GHZ_CHANNELS: frozenset[int] = frozenset(range(1, 15))  # 1-14


def _split_host_port(value: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if sep == "":
        raise ValueError(f"Expected HOST:PORT, got: {value!r}")
    try:
        port_int = int(port)
    except ValueError:
        raise ValueError(f"Invalid port number in {value!r}: {port!r} is not an integer") from None
    if not (1 <= port_int <= 65535):
        raise ValueError(f"Port number in {value!r} must be 1–65535, got {port_int}")
    return host, port_int


def _resolve_config_path(path_text: str, config_path: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return config_path.resolve().parent / path


def _coerce_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be an integer-like value, got {value!r}")
    return int(value)


def _coerce_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be a numeric value, got {value!r}")
    return float(value)


@dataclass(slots=True)
class APSelfHealConfig:
    """Configuration for the Wi-Fi AP self-heal watchdog."""

    enabled: bool
    diagnostics_lookback_minutes: int
    min_restart_interval_seconds: int
    allow_disable_resolved_stub_listener: bool
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
    """Signal processing parameters (sample rate, buffer size, client TTL)."""

    sample_rate_hz: int
    waveform_seconds: int
    client_ttl_seconds: int
    accel_scale_g_per_lsb: float | None

    def __post_init__(self) -> None:
        # --- positive-integer guards ------------------------------------------------
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

        # --- buffer memory bound: sample_rate_hz * waveform_seconds ----------------
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


@dataclass(slots=True)
class LoggingConfig:
    """Run-logging configuration (file path, sample rate, history DB, timeouts)."""

    log_metrics: bool
    metrics_log_hz: int
    no_data_timeout_s: float
    sensor_model: str
    history_db_path: Path
    persist_history_db: bool
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
class AppConfig:
    """Full application configuration assembled from the YAML config file."""

    ap: APConfig
    server: ServerConfig
    udp: UDPConfig
    processing: ProcessingConfig
    logging: LoggingConfig
    gps: GPSConfig
    update: UpdateConfig
    config_path: Path
    repo_dir: Path = REPO_DIR


def _read_config_file(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except PermissionError:
        raise ValueError(f"Cannot read config file {path}: permission denied") from None
    except yaml.YAMLError as exc:
        raise ValueError(f"Config file {path} contains invalid YAML: {exc}") from None
    if not is_json_object(data):
        raise ValueError(f"{path} must contain a YAML object at the top level.")
    return data


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load, validate, and return the application configuration.

    Reads *config_path* (or the default ``config.yaml`` next to this module),
    deep-merges with documented defaults, and returns a fully validated
    ``AppConfig``.
    """
    path = config_path or (SERVER_DIR / "config.yaml")
    path = path.resolve()
    if config_path is not None and not path.exists():
        raise FileNotFoundError(f"Explicitly specified config file does not exist: {path}")
    override = _read_config_file(path)
    merged = deep_merge(DEFAULT_CONFIG, override)
    ap_cfg = _require_config_section(merged.get("ap", {}), "ap")
    server_cfg = _require_config_section(merged.get("server", {}), "server")
    udp_cfg = _require_config_section(merged.get("udp", {}), "udp")
    processing_cfg = _require_config_section(merged.get("processing", {}), "processing")
    logging_cfg = _require_config_section(merged.get("logging", {}), "logging")
    gps_cfg = _require_config_section(merged.get("gps", {}), "gps")
    update_cfg = _require_config_section(merged.get("update", {}), "update")
    default_logging_cfg = _require_config_section(
        DEFAULT_CONFIG.get("logging", {}),
        "default logging",
    )
    default_gps_cfg = _require_config_section(DEFAULT_CONFIG.get("gps", {}), "default gps")
    default_update_cfg = _require_config_section(
        DEFAULT_CONFIG.get("update", {}),
        "default update",
    )
    log_metrics = bool(logging_cfg.get("log_metrics", True))

    data_host, data_port = _split_host_port(str(udp_cfg["data_listen"]))
    control_host, control_port = _split_host_port(str(udp_cfg["control_listen"]))

    accel_scale_raw = processing_cfg.get("accel_scale_g_per_lsb")
    accel_scale = float(accel_scale_raw) if isinstance(accel_scale_raw, NUMERIC_TYPES) else None  # type: ignore[arg-type]
    if accel_scale is not None and accel_scale <= 0:
        LOGGER.warning(
            "processing.accel_scale_g_per_lsb=%s is not positive — using auto-detection",
            accel_scale_raw,
        )
        accel_scale = None

    ap_channel = _coerce_int(ap_cfg["channel"], "ap.channel")
    if ap_channel not in VALID_24GHZ_CHANNELS:
        raise ValueError(f"ap.channel must be 1-14 for 2.4 GHz, got {ap_channel}")

    server_port = _coerce_int(server_cfg["port"], "server.port")
    if not 1 <= server_port <= 65535:
        raise ValueError(f"server.port must be 1-65535, got {server_port}")

    ap_ip_raw = str(ap_cfg["ip"])
    try:
        ipaddress.IPv4Interface(ap_ip_raw)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise ValueError(f"ap.ip must be a valid IPv4 address or CIDR, got {ap_ip_raw!r}") from None

    self_heal_cfg = _require_config_section(ap_cfg.get("self_heal", {}), "ap.self_heal")
    default_ap_cfg = _require_config_section(DEFAULT_CONFIG.get("ap", {}), "default ap")
    self_heal_defaults = _require_config_section(
        default_ap_cfg.get("self_heal", {}),
        "default ap.self_heal",
    )
    app_config = AppConfig(
        ap=APConfig(
            ssid=str(ap_cfg["ssid"]),
            psk=str(ap_cfg["psk"]),
            ip=str(ap_cfg["ip"]),
            channel=ap_channel,
            ifname=str(ap_cfg["ifname"]),
            con_name=str(ap_cfg["con_name"]),
            self_heal=APSelfHealConfig(
                enabled=bool(self_heal_cfg.get("enabled", True)),
                diagnostics_lookback_minutes=_coerce_int(
                    self_heal_cfg.get("diagnostics_lookback_minutes", 5),
                    "ap.self_heal.diagnostics_lookback_minutes",
                ),
                min_restart_interval_seconds=_coerce_int(
                    self_heal_cfg.get("min_restart_interval_seconds", 120),
                    "ap.self_heal.min_restart_interval_seconds",
                ),
                allow_disable_resolved_stub_listener=bool(
                    self_heal_cfg.get("allow_disable_resolved_stub_listener", False),
                ),
                state_file=_resolve_config_path(
                    str(self_heal_cfg.get("state_file", str(self_heal_defaults["state_file"]))),
                    path,
                ),
            ),
        ),
        server=ServerConfig(
            host=str(server_cfg["host"]),
            port=server_port,
        ),
        udp=UDPConfig(
            data_host=data_host,
            data_port=data_port,
            control_host=control_host,
            control_port=control_port,
            data_queue_maxsize=max(
                1,
                _coerce_int(udp_cfg.get("data_queue_maxsize", 1024), "udp.data_queue_maxsize"),
            ),
        ),
        processing=ProcessingConfig(
            sample_rate_hz=_coerce_int(
                processing_cfg["sample_rate_hz"],
                "processing.sample_rate_hz",
            ),
            waveform_seconds=_coerce_int(
                processing_cfg["waveform_seconds"],
                "processing.waveform_seconds",
            ),
            client_ttl_seconds=_coerce_int(
                processing_cfg.get("client_ttl_seconds", 120),
                "processing.client_ttl_seconds",
            ),
            accel_scale_g_per_lsb=accel_scale,
        ),  # NOTE: ProcessingConfig.__post_init__ validates & clamps all fields
        logging=LoggingConfig(
            log_metrics=log_metrics,
            metrics_log_hz=_coerce_int(logging_cfg["metrics_log_hz"], "logging.metrics_log_hz"),
            no_data_timeout_s=_coerce_float(
                logging_cfg.get(
                    "no_data_timeout_s",
                    default_logging_cfg["no_data_timeout_s"],
                ),
                "logging.no_data_timeout_s",
            ),
            sensor_model=str(logging_cfg.get("sensor_model", "ADXL345")),
            history_db_path=_resolve_config_path(
                str(
                    logging_cfg.get(
                        "history_db_path",
                        default_logging_cfg["history_db_path"],
                    ),
                ),
                path,
            ),
            persist_history_db=bool(
                logging_cfg.get("persist_history_db", default_logging_cfg["persist_history_db"]),
            ),
            shutdown_analysis_timeout_s=_coerce_float(
                logging_cfg.get(
                    "shutdown_analysis_timeout_s",
                    default_logging_cfg["shutdown_analysis_timeout_s"],
                ),
                "logging.shutdown_analysis_timeout_s",
            ),
            app_log_path=_resolve_config_path(
                str(logging_cfg.get("app_log_path", default_logging_cfg["app_log_path"])),
                path,
            ),
        ),
        gps=GPSConfig(
            gps_enabled=bool(gps_cfg["gps_enabled"]),
            gpsd_host=str(gps_cfg.get("gpsd_host", default_gps_cfg["gpsd_host"])),
            gpsd_port=_coerce_int(
                gps_cfg.get("gpsd_port", default_gps_cfg["gpsd_port"]),
                "gps.gpsd_port",
            ),
        ),
        update=UpdateConfig(
            rollback_dir=Path(
                str(update_cfg.get("rollback_dir", default_update_cfg["rollback_dir"])),
            ),
        ),
        config_path=path,
    )
    LOGGER.info(
        "Loaded config=%s history_db_path=%s",
        app_config.config_path,
        app_config.logging.history_db_path,
    )
    return app_config
