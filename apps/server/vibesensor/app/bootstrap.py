"""FastAPI application factory and CLI entry point.

Service construction lives in ``container.py`` and runtime state lives in
``runtime_state.py``. This module creates the FastAPI app, wires the lifespan,
and serves static assets.
"""

from __future__ import annotations

import argparse
import asyncio
import errno
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from vibesensor.adapters.http import create_router
from vibesensor.adapters.http.error_boundary import install_http_exception_handlers
from vibesensor.adapters.http.middleware import install_request_logging_middleware
from vibesensor.adapters.udp.udp_data_rx import start_udp_data_receiver
from vibesensor.app.config_loader import load_config
from vibesensor.app.container import build_runtime
from vibesensor.app.runtime_state import AppRuntime
from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime
from vibesensor.shared.process_settings import (
    CONFIG_PATH_ENV,
    export_config_path_env,
    load_bootstrap_env_settings,
)
from vibesensor.shared.structured_logging import StructuredLogFormatter

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

_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_LOG_BACKUP_COUNT = 3
_CONFIG_PATH_ENV = CONFIG_PATH_ENV


def _install_runtime_event_loop_policy() -> None:
    """Install the canonical runtime event-loop policy for this platform."""
    if not sys.platform.startswith("linux"):
        return
    if type(asyncio.get_event_loop_policy()).__module__.startswith("uvloop"):
        return
    try:
        import uvloop
    except ImportError as exc:
        raise RuntimeError(
            "uvloop is required on Linux runtimes; reinstall the backend dependencies.",
        ) from exc
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


def _setup_file_logging(log_path: Path | None) -> None:
    """Attach a RotatingFileHandler to the root logger when *log_path* is set."""
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(StructuredLogFormatter())
        logging.getLogger().addHandler(handler)
        LOGGER.info("File logging enabled: %s", log_path)
    except OSError:
        LOGGER.warning("Failed to set up file logging at %s", log_path, exc_info=True)


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the VibeSensor FastAPI application."""
    _install_runtime_event_loop_policy()
    config = load_config(config_path)
    bootstrap_settings = load_bootstrap_env_settings()
    _setup_file_logging(config.logging.app_log_path)
    runtime = build_runtime(config)
    lifecycle = LifecycleManager(
        runtime=LifecycleRuntime(
            health_state=runtime.lifecycle.health_state,
            history_db_path=config.logging.history_db_path,
            udp_data_host=config.udp.data_host,
            udp_data_port=config.udp.data_port,
            udp_data_queue_maxsize=config.udp.data_queue_maxsize,
            gpsd_host=config.gps.gpsd_host,
            gpsd_port=config.gps.gpsd_port,
            shutdown_analysis_timeout_s=config.logging.shutdown_analysis_timeout_s,
            registry=runtime.lifecycle.registry,
            processor=runtime.lifecycle.processor,
            control_plane=runtime.lifecycle.control_plane,
            processing_loop=runtime.lifecycle.processing_loop,
            ws_hub=runtime.lifecycle.ws_hub,
            ws_broadcast=runtime.lifecycle.ws_broadcast,
            run_recorder=runtime.lifecycle.run_recorder,
            gps_monitor=runtime.lifecycle.gps_monitor,
            obd_runner=runtime.lifecycle.obd_runner,
            update_manager=runtime.lifecycle.update_manager,
            esp_flash_manager=runtime.lifecycle.esp_flash_manager,
            worker_pool=runtime.lifecycle.worker_pool,
            history_db=runtime.lifecycle.history_db,
        ),
        start_udp_receiver=start_udp_data_receiver,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await lifecycle.start()
        except asyncio.CancelledError:
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


def _run_server(
    app_target: FastAPI | str,
    *,
    host: str,
    port: int,
    reload: bool = False,
    factory: bool = False,
) -> None:
    """Run uvicorn for the given app target with the common server settings."""
    uvicorn.run(
        app_target,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
        reload=reload,
        factory=factory,
    )


def _run_server_with_port_fallback(
    app_target: FastAPI | str,
    *,
    host: str,
    port: int,
    reload: bool = False,
    factory: bool = False,
) -> None:
    """Run uvicorn on the configured port, retrying the backup port on bind errors."""
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
        help="Enable uvicorn auto-reload for local development.",
    )
    args = parser.parse_args()

    if args.reload:
        config = load_config(args.config)
        host = config.server.host
        port = config.server.port
        export_config_path_env(args.config)
        _run_server_with_port_fallback(
            "vibesensor.app.bootstrap:create_app_from_env",
            host=host,
            port=port,
            reload=True,
            factory=True,
        )
        return

    runtime_app = create_app(config_path=args.config)
    runtime: AppRuntime = runtime_app.state.runtime
    _run_server_with_port_fallback(
        runtime_app,
        host=runtime.config.server.host,
        port=runtime.config.server.port,
    )


if __name__ == "__main__":
    main()
