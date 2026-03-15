"""Application bootstrap and dependency wiring."""

from __future__ import annotations

from typing import Any

__all__ = [
    "AppConfig",
    "BACKUP_SERVER_PORT",
    "DEFAULT_CONFIG",
    "build_runtime",
    "create_app",
    "create_history_db",
    "load_config",
    "main",
    "resolve_accel_scale_g_per_lsb",
]


def __getattr__(name: str) -> Any:
    if name in {"BACKUP_SERVER_PORT", "create_app", "main"}:
        from .bootstrap import BACKUP_SERVER_PORT, create_app, main

        exports = {
            "BACKUP_SERVER_PORT": BACKUP_SERVER_PORT,
            "create_app": create_app,
            "main": main,
        }
        return exports[name]
    if name in {"build_runtime", "create_history_db", "resolve_accel_scale_g_per_lsb"}:
        from .container import build_runtime, create_history_db, resolve_accel_scale_g_per_lsb

        exports = {
            "build_runtime": build_runtime,
            "create_history_db": create_history_db,
            "resolve_accel_scale_g_per_lsb": resolve_accel_scale_g_per_lsb,
        }
        return exports[name]
    if name in {"AppConfig", "DEFAULT_CONFIG", "load_config"}:
        from .settings import DEFAULT_CONFIG, AppConfig, load_config

        exports = {
            "AppConfig": AppConfig,
            "DEFAULT_CONFIG": DEFAULT_CONFIG,
            "load_config": load_config,
        }
        return exports[name]
    raise AttributeError(name)
