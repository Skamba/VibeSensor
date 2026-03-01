from __future__ import annotations

import ipaddress
import logging
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from vibesensor_shared.contracts import NETWORK_PORTS

SERVER_DIR = Path(__file__).resolve().parents[1]
"""Root of the ``apps/server/`` package tree."""

REPO_DIR = SERVER_DIR.parents[1]
LOGGER = logging.getLogger(__name__)

DEFAULT_UDP_DATA_PORT = int(NETWORK_PORTS["server_udp_data"])
DEFAULT_UDP_CONTROL_PORT = int(NETWORK_PORTS["server_udp_control"])

VALID_24GHZ_CHANNELS: set[int] = set(range(1, 15))  # 1-14

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
    "udp": {
        "data_listen": f"0.0.0.0:{DEFAULT_UDP_DATA_PORT}",
        "control_listen": f"0.0.0.0:{DEFAULT_UDP_CONTROL_PORT}",
        "data_queue_maxsize": 1024,
    },
    "processing": {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "waveform_display_hz": 120,
        "ui_push_hz": 10,
        "ui_heavy_push_hz": 4,
        "fft_update_hz": 4,
        "fft_n": 2048,
        "spectrum_min_hz": 5.0,
        "spectrum_max_hz": 200,
        "client_ttl_seconds": 120,
        "accel_scale_g_per_lsb": None,
    },
    "logging": {
        "log_metrics": True,
        "metrics_log_path": "data/metrics.jsonl",
        "metrics_log_hz": 4,
        "no_data_timeout_s": 15.0,
        "sensor_model": "ADXL345",
        "persist_history_db": True,
        "shutdown_analysis_timeout_s": 30,
    },
    "storage": {
        "clients_json_path": "data/clients.json",
    },
    "gps": {"gps_enabled": True},
    "update": {
        "server_repo": "Skamba/VibeSensor",
        "rollback_dir": "/var/lib/vibesensor/rollback",
    },
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
    try:
        return host, int(port)
    except ValueError:
        raise ValueError(f"Invalid port number in {value!r}: {port!r} is not an integer") from None


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

    def __post_init__(self) -> None:
        if not isinstance(self.port, int) or not (1 <= self.port <= 65535):
            raise ValueError(f"ServerConfig.port must be 1–65535, got {self.port!r}")


@dataclass(slots=True)
class UDPConfig:
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
                f"UDPConfig.data_queue_maxsize must be ≥1, got {self.data_queue_maxsize!r}"
            )


@dataclass(slots=True)
class ProcessingConfig:
    sample_rate_hz: int
    waveform_seconds: int
    waveform_display_hz: int
    ui_push_hz: int
    ui_heavy_push_hz: int
    fft_update_hz: int
    fft_n: int
    spectrum_min_hz: float
    spectrum_max_hz: int
    client_ttl_seconds: int
    accel_scale_g_per_lsb: float | None

    def __post_init__(self) -> None:
        _cfg_logger = logging.getLogger(__name__)
        # --- positive-integer guards ------------------------------------------------
        _POS_FIELDS: dict[str, int] = {
            "sample_rate_hz": 1,
            "waveform_seconds": 1,
            "waveform_display_hz": 1,
            "ui_push_hz": 1,
            "ui_heavy_push_hz": 1,
            "fft_update_hz": 1,
            "spectrum_max_hz": 1,
            "client_ttl_seconds": 1,
        }
        for field_name, minimum in _POS_FIELDS.items():
            val = getattr(self, field_name)
            if val < minimum:
                clamped = minimum
                _cfg_logger.warning(
                    "processing.%s=%s is below minimum %s — clamped to %s",
                    field_name,
                    val,
                    minimum,
                    clamped,
                )
                object.__setattr__(self, field_name, clamped)

        # --- fft_n must be >= 16 and a power of 2 ----------------------------------
        if self.fft_n < 16:
            _cfg_logger.warning(
                "processing.fft_n=%s is below minimum 16 — clamped to 16",
                self.fft_n,
            )
            object.__setattr__(self, "fft_n", 16)
        elif self.fft_n & (self.fft_n - 1) != 0:
            # Round up to next power of 2
            next_pow2 = 1 << (self.fft_n - 1).bit_length()
            _cfg_logger.warning(
                "processing.fft_n=%s is not a power of 2 — rounded up to %s",
                self.fft_n,
                next_pow2,
            )
            object.__setattr__(self, "fft_n", next_pow2)

        _MAX_FFT_N = 65536
        if self.fft_n > _MAX_FFT_N:
            _cfg_logger.warning(
                "processing.fft_n=%s exceeds maximum %s — clamped",
                self.fft_n,
                _MAX_FFT_N,
            )
            object.__setattr__(self, "fft_n", _MAX_FFT_N)

        # --- spectrum_min_hz must be non-negative ----------------------------------
        if self.spectrum_min_hz < 0:
            _cfg_logger.warning(
                "processing.spectrum_min_hz=%s is negative — clamped to 0",
                self.spectrum_min_hz,
            )
            object.__setattr__(self, "spectrum_min_hz", 0.0)

        # --- spectrum_max_hz must be below Nyquist (sample_rate_hz / 2) -------------
        nyquist = self.sample_rate_hz // 2
        if nyquist > 0 and self.spectrum_max_hz >= nyquist:
            clamped = nyquist - 1 if nyquist > 1 else 1
            _cfg_logger.warning(
                "processing.spectrum_max_hz=%s >= Nyquist (%s) — clamped to %s",
                self.spectrum_max_hz,
                nyquist,
                clamped,
            )
            object.__setattr__(self, "spectrum_max_hz", clamped)


@dataclass(slots=True)
class LoggingConfig:
    log_metrics: bool
    metrics_log_path: Path
    metrics_log_hz: int
    no_data_timeout_s: float
    sensor_model: str
    history_db_path: Path
    persist_history_db: bool
    shutdown_analysis_timeout_s: float

    def __post_init__(self) -> None:
        if not isinstance(self.metrics_log_hz, int) or self.metrics_log_hz < 1:
            object.__setattr__(self, "metrics_log_hz", max(1, int(self.metrics_log_hz or 1)))
        if not isinstance(self.no_data_timeout_s, (int, float)) or self.no_data_timeout_s < 0:
            object.__setattr__(self, "no_data_timeout_s", 15.0)
        if (
            not isinstance(self.shutdown_analysis_timeout_s, (int, float))
            or self.shutdown_analysis_timeout_s < 0
        ):
            object.__setattr__(self, "shutdown_analysis_timeout_s", 30.0)


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
        LOGGER.warning(
            "processing.accel_scale_g_per_lsb=%s is not positive — using auto-detection",
            accel_scale_raw,
        )
        accel_scale = None

    ap_channel = int(merged["ap"]["channel"])
    if ap_channel not in VALID_24GHZ_CHANNELS:
        raise ValueError(f"ap.channel must be 1-14 for 2.4 GHz, got {ap_channel}")

    server_port = int(merged["server"]["port"])
    if not 1 <= server_port <= 65535:
        raise ValueError(f"server.port must be 1-65535, got {server_port}")

    ap_ip_raw = str(merged["ap"]["ip"])
    try:
        ipaddress.IPv4Interface(ap_ip_raw)
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError, ValueError):
        raise ValueError(f"ap.ip must be a valid IPv4 address or CIDR, got {ap_ip_raw!r}") from None

    self_heal_cfg = merged["ap"].get("self_heal", {})
    self_heal_defaults = DEFAULT_CONFIG["ap"]["self_heal"]
    app_config = AppConfig(
        ap=APConfig(
            ssid=str(merged["ap"]["ssid"]),
            psk=str(merged["ap"]["psk"]),
            ip=str(merged["ap"]["ip"]),
            channel=ap_channel,
            ifname=str(merged["ap"]["ifname"]),
            con_name=str(merged["ap"]["con_name"]),
            self_heal=APSelfHealConfig(
                enabled=bool(self_heal_cfg.get("enabled", True)),
                interval_seconds=int(self_heal_cfg.get("interval_seconds", 120)),
                diagnostics_lookback_minutes=int(
                    self_heal_cfg.get("diagnostics_lookback_minutes", 5)
                ),
                min_restart_interval_seconds=int(
                    self_heal_cfg.get("min_restart_interval_seconds", 120)
                ),
                allow_disable_resolved_stub_listener=bool(
                    self_heal_cfg.get("allow_disable_resolved_stub_listener", False)
                ),
                state_file=_resolve_config_path(
                    str(self_heal_cfg.get("state_file", str(self_heal_defaults["state_file"]))),
                    path,
                ),
            ),
        ),
        server=ServerConfig(
            host=str(merged["server"]["host"]),
            port=server_port,
        ),
        udp=UDPConfig(
            data_host=data_host,
            data_port=data_port,
            control_host=control_host,
            control_port=control_port,
            data_queue_maxsize=max(1, int(merged["udp"].get("data_queue_maxsize", 1024))),
        ),
        processing=ProcessingConfig(
            sample_rate_hz=int(merged["processing"]["sample_rate_hz"]),
            waveform_seconds=int(merged["processing"]["waveform_seconds"]),
            waveform_display_hz=int(merged["processing"]["waveform_display_hz"]),
            ui_push_hz=int(merged["processing"]["ui_push_hz"]),
            ui_heavy_push_hz=int(merged["processing"].get("ui_heavy_push_hz", 4)),
            fft_update_hz=int(merged["processing"]["fft_update_hz"]),
            fft_n=int(merged["processing"]["fft_n"]),
            spectrum_min_hz=float(merged["processing"].get("spectrum_min_hz", 5.0)),
            spectrum_max_hz=int(merged["processing"]["spectrum_max_hz"]),
            client_ttl_seconds=int(merged["processing"].get("client_ttl_seconds", 120)),
            accel_scale_g_per_lsb=accel_scale,
        ),  # NOTE: ProcessingConfig.__post_init__ validates & clamps all fields
        logging=LoggingConfig(
            log_metrics=log_metrics,
            metrics_log_path=metrics_log_path,
            metrics_log_hz=int(logging_cfg["metrics_log_hz"]),
            no_data_timeout_s=float(
                logging_cfg.get(
                    "no_data_timeout_s",
                    DEFAULT_CONFIG["logging"]["no_data_timeout_s"],
                )
            ),
            sensor_model=str(logging_cfg.get("sensor_model", "ADXL345")),
            history_db_path=_resolve_config_path(
                str(
                    logging_cfg.get(
                        "history_db_path",
                        str(metrics_log_path.parent / "history.db"),
                    )
                ),
                path,
            ),
            persist_history_db=bool(
                logging_cfg.get(
                    "persist_history_db", DEFAULT_CONFIG["logging"]["persist_history_db"]
                )
            ),
            shutdown_analysis_timeout_s=float(
                logging_cfg.get(
                    "shutdown_analysis_timeout_s",
                    DEFAULT_CONFIG["logging"]["shutdown_analysis_timeout_s"],
                )
            ),
        ),
        gps=GPSConfig(
            gps_enabled=bool(merged["gps"]["gps_enabled"]),
        ),
        clients_json_path=_resolve_config_path(
            str(
                merged.get("storage", {}).get(
                    "clients_json_path", str(DEFAULT_CONFIG["storage"]["clients_json_path"])
                )
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
