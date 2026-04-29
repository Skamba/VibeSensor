"""File loading and validation helpers for application configuration."""

from __future__ import annotations

import ipaddress
import logging
from pathlib import Path

import yaml

from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.json_utils import deep_merge
from vibesensor.shared.types.json_types import JsonObject, is_json_object

from .config_defaults import DEFAULT_CONFIG
from .config_paths import SERVER_DIR
from .config_schema import (
    VALID_24GHZ_CHANNELS,
    APConfig,
    AppConfig,
    APSelfHealConfig,
    GPSConfig,
    LoggingConfig,
    ProcessingConfig,
    ServerConfig,
    TracingConfig,
    UDPConfig,
    UpdateConfig,
)

__all__ = ["load_config"]

LOGGER = logging.getLogger("vibesensor.app.settings")


def _require_config_section(raw: object, section_name: str) -> JsonObject:
    if is_json_object(raw):
        return raw
    raise ValueError(f"config section {section_name!r} must be a YAML object")


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


def _coerce_port(value: object, field_name: str) -> int:
    port = _coerce_int(value, field_name)
    if not 1 <= port <= 65535:
        raise ValueError(f"{field_name} must be 1-65535, got {port}")
    return port


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
    applies precedence ``DEFAULT_CONFIG -> YAML override file -> typed
    validation/clamping``, and returns a fully validated ``AppConfig``.
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
    tracing_cfg = _require_config_section(merged.get("tracing", {}), "tracing")

    data_host = str(udp_cfg["data_host"])
    data_port = _coerce_port(udp_cfg["data_port"], "udp.data_port")
    control_host = str(udp_cfg["control_host"])
    control_port = _coerce_port(udp_cfg["control_port"], "udp.control_port")

    accel_scale_raw = processing_cfg.get("accel_scale_g_per_lsb")
    accel_scale = float(accel_scale_raw) if isinstance(accel_scale_raw, NUMERIC_TYPES) else None
    if accel_scale is not None and accel_scale <= 0:
        LOGGER.warning(
            "processing.accel_scale_g_per_lsb=%s is not positive — using auto-detection",
            accel_scale_raw,
        )
        accel_scale = None

    ap_channel = _coerce_int(ap_cfg["channel"], "ap.channel")
    if ap_channel not in VALID_24GHZ_CHANNELS:
        raise ValueError(f"ap.channel must be 1-14 for 2.4 GHz, got {ap_channel}")

    server_port = _coerce_port(server_cfg["port"], "server.port")

    ap_ip_raw = str(ap_cfg["ip"])
    try:
        ipaddress.IPv4Interface(ap_ip_raw)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise ValueError(f"ap.ip must be a valid IPv4 address or CIDR, got {ap_ip_raw!r}") from None

    self_heal_cfg = _require_config_section(ap_cfg.get("self_heal", {}), "ap.self_heal")
    app_config = AppConfig(
        ap=APConfig(
            ssid=str(ap_cfg["ssid"]),
            psk=str(ap_cfg["psk"]),
            ip=str(ap_cfg["ip"]),
            channel=ap_channel,
            ifname=str(ap_cfg["ifname"]),
            con_name=str(ap_cfg["con_name"]),
            self_heal=APSelfHealConfig(
                enabled=bool(self_heal_cfg["enabled"]),
                diagnostics_lookback_minutes=_coerce_int(
                    self_heal_cfg["diagnostics_lookback_minutes"],
                    "ap.self_heal.diagnostics_lookback_minutes",
                ),
                min_restart_interval_seconds=_coerce_int(
                    self_heal_cfg["min_restart_interval_seconds"],
                    "ap.self_heal.min_restart_interval_seconds",
                ),
                state_file=_resolve_config_path(
                    str(self_heal_cfg["state_file"]),
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
                _coerce_int(udp_cfg["data_queue_maxsize"], "udp.data_queue_maxsize"),
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
            client_live_ttl_seconds=_coerce_int(
                processing_cfg["client_live_ttl_seconds"],
                "processing.client_live_ttl_seconds",
            ),
            client_ttl_seconds=_coerce_int(
                processing_cfg["client_ttl_seconds"],
                "processing.client_ttl_seconds",
            ),
            accel_scale_g_per_lsb=accel_scale,
        ),
        logging=LoggingConfig(
            metrics_log_hz=_coerce_int(logging_cfg["metrics_log_hz"], "logging.metrics_log_hz"),
            no_data_timeout_s=_coerce_float(
                logging_cfg["no_data_timeout_s"],
                "logging.no_data_timeout_s",
            ),
            history_db_path=_resolve_config_path(
                str(logging_cfg["history_db_path"]),
                path,
            ),
            persist_history_db=bool(logging_cfg["persist_history_db"]),
            run_retention_days=_coerce_int(
                logging_cfg["run_retention_days"],
                "logging.run_retention_days",
            ),
            raw_capture_retention_days=_coerce_int(
                logging_cfg["raw_capture_retention_days"],
                "logging.raw_capture_retention_days",
            ),
            shutdown_analysis_timeout_s=_coerce_float(
                logging_cfg["shutdown_analysis_timeout_s"],
                "logging.shutdown_analysis_timeout_s",
            ),
            app_log_path=_resolve_config_path(
                str(logging_cfg["app_log_path"]),
                path,
            ),
        ),
        gps=GPSConfig(
            gps_enabled=bool(gps_cfg["gps_enabled"]),
            gpsd_host=str(gps_cfg["gpsd_host"]),
            gpsd_port=_coerce_int(
                gps_cfg["gpsd_port"],
                "gps.gpsd_port",
            ),
        ),
        update=UpdateConfig(
            rollback_dir=_resolve_config_path(
                str(update_cfg["rollback_dir"]),
                path,
            ),
        ),
        tracing=TracingConfig(
            enabled=bool(tracing_cfg["enabled"]),
            output_path=_resolve_config_path(
                str(tracing_cfg["output_path"]),
                path,
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
