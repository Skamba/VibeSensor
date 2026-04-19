"""Public startup configuration API.

`config_defaults.py` owns YAML runtime defaults, `config_schema.py` owns the
typed deployment dataclasses, `config_loader.py` owns YAML loading/validation,
and `process_settings.py` owns the typed env/process overrides. This facade
preserves the stable `vibesensor.app.settings` import path for production
callers.
"""

from __future__ import annotations

from .config_defaults import DEFAULT_CONFIG, documented_default_config
from .config_loader import load_config
from .config_paths import REPO_DIR, SERVER_DIR
from .config_schema import (
    VALID_24GHZ_CHANNELS,
    APConfig,
    AppConfig,
    APSelfHealConfig,
    GPSConfig,
    LoggingConfig,
    ProcessingConfig,
    ServerConfig,
    UDPConfig,
    UpdateConfig,
)
from .process_settings import (
    CONFIG_PATH_ENV,
    DEFAULT_FIRMWARE_CACHE_DIR,
    DEFAULT_FIRMWARE_CHANNEL,
    DEFAULT_UPDATE_REPO_PATH,
    DEFAULT_UPDATE_ROLLBACK_DIR,
    DEFAULT_UPDATE_STATE_PATH,
    BootstrapEnvSettings,
    UpdateEnvSettings,
    WebSocketEnvSettings,
    export_config_path_env,
    load_bootstrap_env_settings,
    load_update_env_settings,
    load_websocket_env_settings,
    summarize_process_settings,
)

__all__ = [
    "DEFAULT_CONFIG",
    "CONFIG_PATH_ENV",
    "DEFAULT_FIRMWARE_CACHE_DIR",
    "DEFAULT_FIRMWARE_CHANNEL",
    "DEFAULT_UPDATE_REPO_PATH",
    "DEFAULT_UPDATE_ROLLBACK_DIR",
    "DEFAULT_UPDATE_STATE_PATH",
    "REPO_DIR",
    "SERVER_DIR",
    "VALID_24GHZ_CHANNELS",
    "APConfig",
    "APSelfHealConfig",
    "AppConfig",
    "BootstrapEnvSettings",
    "GPSConfig",
    "LoggingConfig",
    "ProcessingConfig",
    "ServerConfig",
    "UDPConfig",
    "UpdateEnvSettings",
    "UpdateConfig",
    "WebSocketEnvSettings",
    "documented_default_config",
    "export_config_path_env",
    "load_config",
    "load_bootstrap_env_settings",
    "load_update_env_settings",
    "load_websocket_env_settings",
    "summarize_process_settings",
]
