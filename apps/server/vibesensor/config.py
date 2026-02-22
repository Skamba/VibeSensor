from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SERVER_DIR = Path(__file__).resolve().parents[1]
"""Root of the ``apps/server/`` package tree."""

REPO_DIR = SERVER_DIR.parents[1]
LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG: dict[str, Any] = {
    "ap": {
        "ssid": "VibeSensor",
        "psk": "",
        "ip": "10.4.0.1/24",
        "channel": 7,
        "ifname": "wlan0",
        "con_name": "VibeSensor-AP",
        "self_heal": {
            "enabled": True,
            "interval_seconds": 120,
            "diagnostics_lookback_minutes": 5,
            "min_restart_interval_seconds": 120,
            "allow_disable_resolved_stub_listener": False,
            "state_file": "data/hotspot-self-heal-state.json",
        },
    },
    "server": {"host": "0.0.0.0", "port": 80},
    "udp": {"data_listen": "0.0.0.0:9000", "control_listen": "0.0.0.0:9001"},
    "processing": {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "waveform_display_hz": 120,
        "ui_push_hz": 10,
        "ui_heavy_push_hz": 4,
        "fft_update_hz": 4,
        "fft_n": 2048,
        "spectrum_max_hz": 200,
        "client_ttl_seconds": 120,
        "accel_scale_g_per_lsb": None,
    },
    "logging": {
        "log_metrics": True,
        "metrics_log_path": "data/metrics.jsonl",
        "metrics_log_hz": 4,
        "sensor_model": "ADXL345",
        "persist_history_db": True,
    },
    "storage": {
        "clients_json_path": "data/clients.json",
    },
    "gps": {"gps_enabled": False},
}


def documented_default_config() -> dict[str, Any]:
    """Return runtime defaults in the shape documented by config.example.yaml."""
    defaults = deepcopy(DEFAULT_CONFIG)
    metrics_log_path = Path(str(defaults["logging"]["metrics_log_path"]))
    defaults["logging"]["history_db_path"] = str(metrics_log_path.parent / "history.db")
    return defaults


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _split_host_port(value: str) -> tuple[str, int]:
    host, sep, port = value.rpartition(":")
    if sep == "":
        raise ValueError(f"Expected HOST:PORT, got: {value!r}")
    return host, int(port)


def _resolve_config_path(path_text: str, config_path: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return config_path.resolve().parent / path


@dataclass(slots=True)
class APSelfHealConfig:
    enabled: bool
    interval_seconds: int
    diagnostics_lookback_minutes: int
    min_restart_interval_seconds: int
    allow_disable_resolved_stub_listener: bool
    state_file: Path


@dataclass(slots=True)
class APConfig:
    ssid: str
    psk: str
    ip: str
    channel: int
    ifname: str
    con_name: str
    self_heal: APSelfHealConfig


@dataclass(slots=True)
class ServerConfig:
    host: str
    port: int


@dataclass(slots=True)
class UDPConfig:
    data_host: str
    data_port: int
    control_host: str
    control_port: int


@dataclass(slots=True)
class ProcessingConfig:
    sample_rate_hz: int
    waveform_seconds: int
    waveform_display_hz: int
    ui_push_hz: int
    ui_heavy_push_hz: int
    fft_update_hz: int
    fft_n: int
    spectrum_max_hz: int
    client_ttl_seconds: int
    accel_scale_g_per_lsb: float | None


@dataclass(slots=True)
class LoggingConfig:
    log_metrics: bool
    metrics_log_path: Path
    metrics_log_hz: int
    sensor_model: str
    history_db_path: Path
    persist_history_db: bool


@dataclass(slots=True)
class GPSConfig:
    gps_enabled: bool


@dataclass(slots=True)
class AppConfig:
    ap: APConfig
    server: ServerConfig
    udp: UDPConfig
    processing: ProcessingConfig
    logging: LoggingConfig
    gps: GPSConfig
    clients_json_path: Path
    config_path: Path
    repo_dir: Path = REPO_DIR


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML object at the top level.")
        return data


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or (SERVER_DIR / "config.yaml")
    path = path.resolve()
    override = _read_config_file(path)
    merged = _deep_merge(DEFAULT_CONFIG, override)
    logging_cfg = merged.get("logging", {})
    metrics_log_path_raw = logging_cfg.get("metrics_log_path")
    log_metrics = bool(logging_cfg.get("log_metrics", True))
    if not isinstance(metrics_log_path_raw, str) or not metrics_log_path_raw.strip():
        if log_metrics:
            raise ValueError(
                "logging.metrics_log_path must be configured when log_metrics is true."
            )
        metrics_log_path_raw = str(DEFAULT_CONFIG["logging"]["metrics_log_path"])
    metrics_log_path = _resolve_config_path(metrics_log_path_raw, path)

    data_host, data_port = _split_host_port(str(merged["udp"]["data_listen"]))
    control_host, control_port = _split_host_port(str(merged["udp"]["control_listen"]))

    accel_scale_raw = merged["processing"].get("accel_scale_g_per_lsb")
    accel_scale = float(accel_scale_raw) if isinstance(accel_scale_raw, (int, float)) else None
    if accel_scale is not None and accel_scale <= 0:
        accel_scale = None

    app_config = AppConfig(
        ap=APConfig(
            ssid=str(merged["ap"]["ssid"]),
            psk=str(merged["ap"]["psk"]),
            ip=str(merged["ap"]["ip"]),
            channel=int(merged["ap"]["channel"]),
            ifname=str(merged["ap"]["ifname"]),
            con_name=str(merged["ap"]["con_name"]),
            self_heal=APSelfHealConfig(
                enabled=bool(merged["ap"].get("self_heal", {}).get("enabled", True)),
                interval_seconds=int(
                    merged["ap"].get("self_heal", {}).get("interval_seconds", 120)
                ),
                diagnostics_lookback_minutes=int(
                    merged["ap"].get("self_heal", {}).get("diagnostics_lookback_minutes", 5)
                ),
                min_restart_interval_seconds=int(
                    merged["ap"].get("self_heal", {}).get("min_restart_interval_seconds", 120)
                ),
                allow_disable_resolved_stub_listener=bool(
                    merged["ap"]
                    .get("self_heal", {})
                    .get("allow_disable_resolved_stub_listener", False)
                ),
                state_file=_resolve_config_path(
                    str(
                        merged["ap"]
                        .get("self_heal", {})
                        .get(
                            "state_file",
                            str(DEFAULT_CONFIG["ap"]["self_heal"]["state_file"]),
                        )
                    ),
                    path,
                ),
            ),
        ),
        server=ServerConfig(
            host=str(merged["server"]["host"]),
            port=int(merged["server"]["port"]),
        ),
        udp=UDPConfig(
            data_host=data_host,
            data_port=data_port,
            control_host=control_host,
            control_port=control_port,
        ),
        processing=ProcessingConfig(
            sample_rate_hz=int(merged["processing"]["sample_rate_hz"]),
            waveform_seconds=int(merged["processing"]["waveform_seconds"]),
            waveform_display_hz=int(merged["processing"]["waveform_display_hz"]),
            ui_push_hz=int(merged["processing"]["ui_push_hz"]),
            ui_heavy_push_hz=int(merged["processing"].get("ui_heavy_push_hz", 4)),
            fft_update_hz=int(merged["processing"]["fft_update_hz"]),
            fft_n=int(merged["processing"]["fft_n"]),
            spectrum_max_hz=int(merged["processing"]["spectrum_max_hz"]),
            client_ttl_seconds=int(merged["processing"].get("client_ttl_seconds", 120)),
            accel_scale_g_per_lsb=accel_scale,
        ),
        logging=LoggingConfig(
            log_metrics=log_metrics,
            metrics_log_path=metrics_log_path,
            metrics_log_hz=int(merged["logging"]["metrics_log_hz"]),
            sensor_model=str(merged["logging"].get("sensor_model", "ADXL345")),
            history_db_path=_resolve_config_path(
                str(
                    merged.get("logging", {}).get(
                        "history_db_path",
                        str(metrics_log_path.parent / "history.db"),
                    )
                ),
                path,
            ),
            persist_history_db=bool(
                merged["logging"].get(
                    "persist_history_db", DEFAULT_CONFIG["logging"]["persist_history_db"]
                )
            ),
        ),
        gps=GPSConfig(
            gps_enabled=bool(merged["gps"]["gps_enabled"]),
        ),
        clients_json_path=_resolve_config_path(
            str(
                merged.get(
                    "storage",
                    {},
                ).get("clients_json_path", str(DEFAULT_CONFIG["storage"]["clients_json_path"]))
            ),
            path,
        ),
        config_path=path,
    )
    LOGGER.info(
        "Loaded config=%s metrics_log_path=%s clients_json_path=%s",
        app_config.config_path,
        app_config.logging.metrics_log_path,
        app_config.clients_json_path,
    )
    return app_config
