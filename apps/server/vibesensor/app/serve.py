"""``vibesensor-server`` supervisor: run Granian on the app factory.

This process only supervises the Granian worker that serves the app; it never
builds the app. It therefore imports Granian, the config loader and logging,
not ``vibesensor.app.bootstrap``: the worker imports that itself. Granian
forks (or spawns) the worker, and whatever this process had imported would
stay resident here as a second copy once the worker's reference counts and
garbage collection touch those pages, about 40 MB on the Pi.
"""

from __future__ import annotations

import argparse
import errno
import logging
import sys
from pathlib import Path

from granian import Granian
from granian.constants import Interfaces, Loops
from granian.log import LogLevels

from vibesensor.app.config_loader import load_config
from vibesensor.common.process_settings import export_config_path_env
from vibesensor.common.structured_logging import configure_logging

__all__ = ["APP_FACTORY_TARGET", "main", "run_server_with_port_fallback"]

LOGGER = logging.getLogger(__name__)

APP_FACTORY_TARGET = "vibesensor.app.bootstrap:create_app_from_env"
"""The app factory the Granian worker imports and calls."""

BACKUP_SERVER_PORT = 8000
"""Fallback HTTP port when the configured port is unavailable (e.g. EACCES
on port 80).  Chosen to be a common unprivileged alternative."""

_BIND_ERROR_NUMBERS: frozenset[int] = frozenset({errno.EACCES, errno.EADDRINUSE, 10013, 10048})
"""OS errno values indicating a port-bind failure (includes Windows equivalents)."""


def _granian_loop() -> Loops:
    """Return the canonical Granian loop implementation for this platform."""
    if sys.platform.startswith("linux"):
        import uvloop

        if not callable(getattr(uvloop, "new_event_loop", None)):
            raise RuntimeError("uvloop is unavailable for Granian startup")
        return Loops.uvloop
    return Loops.asyncio


def _run_server(
    app_target: str,
    *,
    host: str,
    port: int,
    reload: bool = False,
    factory: bool = False,
) -> None:
    """Run Granian for the given app target with the common server settings."""
    server = Granian(
        app_target,
        address=host,
        port=port,
        interface=Interfaces.ASGI,
        log_enabled=True,
        log_level=LogLevels.info,
        loop=_granian_loop(),
        reload=reload,
        factory=factory,
    )
    server.serve()


def run_server_with_port_fallback(
    app_target: str,
    *,
    host: str,
    port: int,
    reload: bool = False,
    factory: bool = False,
) -> None:
    """Run Granian on the configured port, retrying the backup port on bind errors."""
    try:
        _run_server(
            app_target,
            host=host,
            port=port,
            reload=reload,
            factory=factory,
        )
    except OSError as exc:
        if port != 80:
            LOGGER.warning("Failed to bind to configured port %d.", port, exc_info=True)
            raise
        if exc.errno not in _BIND_ERROR_NUMBERS:
            LOGGER.warning("Port 80 startup failed with non-bind OSError.", exc_info=True)
            raise
        LOGGER.warning(
            "Failed to bind to port 80; retrying on backup port %d.",
            BACKUP_SERVER_PORT,
            exc_info=True,
        )
        try:
            _run_server(
                app_target,
                host=host,
                port=BACKUP_SERVER_PORT,
                reload=reload,
                factory=factory,
            )
        except OSError:
            LOGGER.error(
                "Failed to bind to both port 80 and backup port %d.",
                BACKUP_SERVER_PORT,
                exc_info=True,
            )
            raise


def main() -> None:
    """Entry point for the ``vibesensor-server`` CLI command."""
    parser = argparse.ArgumentParser(description="Run VibeSensor server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable Granian auto-reload for local development.",
    )
    args = parser.parse_args()
    configure_logging(None)
    config = load_config(args.config)
    configure_logging(config.logging.app_log_path)
    export_config_path_env(args.config)
    run_server_with_port_fallback(
        APP_FACTORY_TARGET,
        host=config.server.host,
        port=config.server.port,
        reload=args.reload,
        factory=True,
    )


if __name__ == "__main__":
    main()
