"""Public application configuration API.

`config_defaults.py` owns runtime defaults, `config_schema.py` owns the typed
configuration dataclasses, and `config_loader.py` owns YAML loading and
validation. This facade preserves the stable `vibesensor.app.settings` import
path for production callers.
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

__all__ = [
    "DEFAULT_CONFIG",
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
