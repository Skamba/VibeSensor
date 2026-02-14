from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PI_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = PI_DIR.parent

DEFAULT_CONFIG: dict[str, Any] = {
    "ap": {
        "ssid": "VibeSensor",
        "psk": "vibesensor123",
        "ip": "192.168.4.1/24",
        "channel": 7,
        "ifname": "wlan0",
        "con_name": "VibeSensor-AP",
    },
    "server": {"host": "0.0.0.0", "port": 8000},
    "udp": {"data_listen": "0.0.0.0:9000", "control_listen": "0.0.0.0:9001"},
    "processing": {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "waveform_display_hz": 200,
        "ui_push_hz": 20,
        "fft_update_hz": 4,
        "fft_n": 2048,
        "spectrum_max_hz": 200,
    },
    "logging": {
        "log_metrics": True,
        "metrics_csv_path": "pi/data/metrics.csv",
        "metrics_log_hz": 4,
    },
    "gps": {"gps_enabled": False, "gps_speed_only": True},
}


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


def _resolve_repo_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return REPO_DIR / path


@dataclass(slots=True)
class APConfig:
    ssid: str
    psk: str
    ip: str
    channel: int
    ifname: str
    con_name: str


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
    fft_update_hz: int
    fft_n: int
    spectrum_max_hz: int


@dataclass(slots=True)
class LoggingConfig:
    log_metrics: bool
    metrics_csv_path: Path
    metrics_log_hz: int


@dataclass(slots=True)
class GPSConfig:
    gps_enabled: bool
    gps_speed_only: bool


@dataclass(slots=True)
class AppConfig:
    ap: APConfig
    server: ServerConfig
    udp: UDPConfig
    processing: ProcessingConfig
    logging: LoggingConfig
    gps: GPSConfig
    config_path: Path
    repo_dir: Path = REPO_DIR

    @property
    def clients_json_path(self) -> Path:
        return self.repo_dir / "pi" / "data" / "clients.json"


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML object at the top level.")
        return data


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or (PI_DIR / "config.yaml")
    override = _read_config_file(path)
    merged = _deep_merge(DEFAULT_CONFIG, override)

    data_host, data_port = _split_host_port(str(merged["udp"]["data_listen"]))
    control_host, control_port = _split_host_port(str(merged["udp"]["control_listen"]))

    return AppConfig(
        ap=APConfig(
            ssid=str(merged["ap"]["ssid"]),
            psk=str(merged["ap"]["psk"]),
            ip=str(merged["ap"]["ip"]),
            channel=int(merged["ap"]["channel"]),
            ifname=str(merged["ap"]["ifname"]),
            con_name=str(merged["ap"]["con_name"]),
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
            fft_update_hz=int(merged["processing"]["fft_update_hz"]),
            fft_n=int(merged["processing"]["fft_n"]),
            spectrum_max_hz=int(merged["processing"]["spectrum_max_hz"]),
        ),
        logging=LoggingConfig(
            log_metrics=bool(merged["logging"]["log_metrics"]),
            metrics_csv_path=_resolve_repo_path(str(merged["logging"]["metrics_csv_path"])),
            metrics_log_hz=int(merged["logging"]["metrics_log_hz"]),
        ),
        gps=GPSConfig(
            gps_enabled=bool(merged["gps"]["gps_enabled"]),
            gps_speed_only=bool(merged["gps"]["gps_speed_only"]),
        ),
        config_path=path,
    )

