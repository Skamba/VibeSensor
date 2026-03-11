"""FastAPI application factory and CLI entry point.

Service construction lives in ``runtime/builders.py``.  Runtime coordination
lives in the ``runtime/`` package.  This module creates the FastAPI app,
wires the lifespan, and serves static assets.
"""

from __future__ import annotations

import argparse
import errno
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .routes import create_router
from .runtime import RuntimeState
from .runtime.builders import build_runtime
from .runtime.lifecycle import LifecycleManager

__all__ = ["create_app", "main"]

LOGGER = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent
"""Resolved directory containing this package, cached at import time to avoid
repeated filesystem resolution in ``create_app()``."""

BACKUP_SERVER_PORT = 8000
"""Fallback HTTP port when the configured port is unavailable (e.g. EACCES
on port 80).  Chosen to be a common unprivileged alternative."""

_BIND_ERROR_NUMBERS: frozenset[int] = frozenset({errno.EACCES, errno.EADDRINUSE, 10013, 10048})
"""OS errno values indicating a port-bind failure (includes Windows equivalents)."""

_LOG_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_LOG_BACKUP_COUNT = 3


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
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        LOGGER.info("File logging enabled: %s", log_path)
    except OSError:
        LOGGER.warning("Failed to set up file logging at %s", log_path, exc_info=True)


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the VibeSensor FastAPI application."""
    config = load_config(config_path)
    _setup_file_logging(config.logging.app_log_path)
    runtime = build_runtime(config)
    lifecycle = LifecycleManager(runtime=runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await lifecycle.start()
        except Exception:
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
    app.include_router(create_router(runtime))
    if os.getenv("VIBESENSOR_SERVE_STATIC", "1") == "1":
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


app: FastAPI | None = (
    create_app()
    if __name__ != "__main__" and os.getenv("VIBESENSOR_DISABLE_AUTO_APP", "0") != "1"
    else None
)


def main() -> None:
    """Entry point for the ``vibesensor-server`` CLI command."""
    parser = argparse.ArgumentParser(description="Run VibeSensor server")
    parser.add_argument("--config", type=Path, default=None, help="Path to config YAML")
    args = parser.parse_args()

    runtime_app = create_app(config_path=args.config)
    runtime: RuntimeState = runtime_app.state.runtime
    host = runtime.config.server.host
    port = runtime.config.server.port
    try:
        uvicorn.run(
            runtime_app,
            host=host,
            port=port,
            log_level="info",
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
            uvicorn.run(
                runtime_app,
                host=host,
                port=BACKUP_SERVER_PORT,
                log_level="info",
            )
        except OSError:
            LOGGER.error(
                "Failed to bind to both port 80 and backup port %d.",
                BACKUP_SERVER_PORT,
                exc_info=True,
            )
            raise


if __name__ == "__main__":
    main()
