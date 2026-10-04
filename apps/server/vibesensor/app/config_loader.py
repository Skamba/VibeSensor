"""File loading and validation helpers for application configuration."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from vibesensor.app.config_defaults import DEFAULT_CONFIG
from vibesensor.app.config_paths import SERVER_DIR
from vibesensor.app.config_schema import (
    APConfig,
    AppConfig,
    GPSConfig,
    LoggingConfig,
    RecordingConfig,
    ServerConfig,
    UDPConfig,
)
from vibesensor.common.json_types import JsonObject, is_json_object
from vibesensor.common.json_utils import deep_merge

__all__ = ["load_config"]

LOGGER = logging.getLogger("vibesensor.app.settings")


def _require_config_section(raw: object, section_name: str) -> JsonObject:
    if is_json_object(raw):
        return raw
    raise ValueError(f"config section {section_name!r} must be a YAML object")


def _resolve_path(path_text: str, base_dir: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return base_dir / path


def _coerce_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be an integer-like value, got {value!r}")
    return int(value)


def _coerce_port(value: object, field_name: str) -> int:
    port = _coerce_int(value, field_name)
    if not 1 <= port <= 65535:
        raise ValueError(f"{field_name} must be 1-65535, got {port}")
    return port


def _coerce_positive_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ValueError(f"{field_name} must be a positive number, got {value!r}")
    return float(value)


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


def _warn_unsupported_keys(override: JsonObject, defaults: JsonObject, prefix: str = "") -> None:
    """Log keys that are not (or no longer) configurable; they are ignored."""
    for key, value in override.items():
        dotted = f"{prefix}{key}"
        if key not in defaults:
            LOGGER.warning("Ignoring unsupported config key %s", dotted)
            continue
        default_value = defaults[key]
        if is_json_object(value) and is_json_object(default_value):
            _warn_unsupported_keys(value, default_value, f"{dotted}.")


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load, validate, and return the application configuration.

    Reads *config_path* (or the default ``config.yaml`` next to this module),
    applies precedence ``DEFAULT_CONFIG -> YAML override file -> typed
    validation``, and returns a fully validated ``AppConfig``. Keys that are not
    part of ``DEFAULT_CONFIG`` (for example settings removed in older releases)
    are logged and ignored.
    """
    path = config_path or (SERVER_DIR / "config.yaml")
    path = path.resolve()
    if config_path is not None and not path.exists():
        raise FileNotFoundError(f"Explicitly specified config file does not exist: {path}")
    override = _read_config_file(path)
    _warn_unsupported_keys(override, DEFAULT_CONFIG)
    merged = deep_merge(DEFAULT_CONFIG, override)
    ap_cfg = _require_config_section(merged.get("ap", {}), "ap")
    server_cfg = _require_config_section(merged.get("server", {}), "server")
    udp_cfg = _require_config_section(merged.get("udp", {}), "udp")
    logging_cfg = _require_config_section(merged.get("logging", {}), "logging")
    gps_cfg = _require_config_section(merged.get("gps", {}), "gps")
    recording_cfg = _require_config_section(merged.get("recording", {}), "recording")

    # The history DB path defines the data directory; a relative app log path
    # follows it, so a read-only config directory (/etc on the Pi) never hosts logs.
    history_db_path = _resolve_path(str(logging_cfg["history_db_path"]), path.parent)
    app_log_path_raw = logging_cfg.get("app_log_path")
    app_config = AppConfig(
        ap=APConfig(ssid=str(ap_cfg["ssid"]), psk=str(ap_cfg["psk"])),
        server=ServerConfig(
            host=str(server_cfg["host"]),
            port=_coerce_port(server_cfg["port"], "server.port"),
        ),
        udp=UDPConfig(
            data_host=str(udp_cfg["data_host"]),
            data_port=_coerce_port(udp_cfg["data_port"], "udp.data_port"),
            control_host=str(udp_cfg["control_host"]),
            control_port=_coerce_port(udp_cfg["control_port"], "udp.control_port"),
        ),
        logging=LoggingConfig(
            history_db_path=history_db_path,
            app_log_path=(
                None
                if app_log_path_raw is None
                else _resolve_path(str(app_log_path_raw), history_db_path.parent)
            ),
        ),
        gps=GPSConfig(
            gps_enabled=bool(gps_cfg["gps_enabled"]),
            gpsd_port=_coerce_port(gps_cfg["gpsd_port"], "gps.gpsd_port"),
        ),
        recording=RecordingConfig(
            max_duration_s=_coerce_positive_float(
                recording_cfg["max_duration_s"], "recording.max_duration_s"
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
