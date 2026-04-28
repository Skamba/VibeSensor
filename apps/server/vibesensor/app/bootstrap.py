"""FastAPI application factory and CLI entry point.

Service construction lives in ``container.py`` and runtime state lives in
``runtime_state.py``. This module creates the FastAPI app, wires the lifespan,
and serves static assets.
"""

from __future__ import annotations

import argparse
import errno
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from granian import Granian
from granian.constants import Interfaces, Loops
from granian.log import LogLevels

from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.error_boundary import install_http_exception_handlers
from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.adapters.udp.udp_data_rx import start_udp_data_receiver
from vibesensor.app.config_loader import load_config
from vibesensor.app.container import build_runtime
from vibesensor.infra.runtime.lifecycle import LifecycleManager
from vibesensor.shared.process_settings import (
    CONFIG_PATH_ENV,
    export_config_path_env,
    load_bootstrap_env_settings,
)
from vibesensor.shared.structured_logging import configure_logging
from vibesensor.shared.tracing import configure_tracing, shutdown_tracing

__all__ = ["create_app", "create_app_from_env", "main"]

LOGGER = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
"""Resolved directory containing this package, cached at import time to avoid
repeated filesystem resolution in ``create_app()``."""

BACKUP_SERVER_PORT = 8000
"""Fallback HTTP port when the configured port is unavailable (e.g. EACCES
on port 80).  Chosen to be a common unprivileged alternative."""

_BIND_ERROR_NUMBERS: frozenset[int] = frozenset({errno.EACCES, errno.EADDRINUSE, 10013, 10048})
"""OS errno values indicating a port-bind failure (includes Windows equivalents)."""

_CONFIG_PATH_ENV = CONFIG_PATH_ENV


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the VibeSensor FastAPI application."""
    configure_logging(None)
    config = load_config(config_path)
    bootstrap_settings = load_bootstrap_env_settings()
    configure_logging(config.logging.app_log_path)
    configure_tracing(config.tracing)
    runtime = build_runtime(config)
    lifecycle = LifecycleManager(
        runtime=runtime.lifecycle.lifecycle_runtime(),
        start_udp_receiver=start_udp_data_receiver,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cancelled_exc_class = anyio.get_cancelled_exc_class()
        try:
            await lifecycle.start()
        except cancelled_exc_class:
            LOGGER.info("Runtime lifecycle start cancelled; cleaning up before re-raise")
            await lifecycle.stop()
            raise
        except (OSError, RuntimeError):
            LOGGER.error(
                "Runtime lifecycle start failed; cleaning up before re-raise",
                exc_info=True,
            )
            await lifecycle.stop()
            raise
        try:
            yield
        finally:
            await lifecycle.stop()
            shutdown_tracing()

    app = FastAPI(title="VibeSensor", lifespan=lifespan)
    app.state.runtime = runtime
    install_http_exception_handlers(app)
    install_request_logging_middleware(app)
    app.include_router(create_router(runtime.router))
    if bootstrap_settings.serve_static:
        static_dir = _PACKAGE_DIR / "static"
        if not (static_dir / "index.html").exists():
            message = (
                "UI not built. Run tools/build_ui_static.py, build the Docker image, "
                "or install a release wheel."
            )
            LOGGER.error(
                "%s Missing index.html in %s",
                message,
                static_dir,
            )
            raise RuntimeError(message)
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="public")

    return app


def create_app_from_env() -> FastAPI:
    """Create the app using the config path exported for reload mode."""
    return create_app(config_path=load_bootstrap_env_settings().config_path)


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


def _run_server_with_port_fallback(
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
    configure_tracing(config.tracing)
    export_config_path_env(args.config)
    _run_server_with_port_fallback(
        "vibesensor.app.bootstrap:create_app_from_env",
        host=config.server.host,
        port=config.server.port,
        reload=args.reload,
        factory=True,
    )


if __name__ == "__main__":
    main()
