"""FastAPI application factory and CLI entry point.

Service construction lives in ``bootstrap.py``.  Runtime coordination
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
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .bootstrap import build_services
from .config import SERVER_DIR, load_config
from .routes import create_router
from .runtime import RuntimeState

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


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the VibeSensor FastAPI application."""
    config = load_config(config_path)
    runtime = build_services(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await runtime.start()
        except Exception:
            LOGGER.error("RuntimeState.start() failed; cleaning up before re-raise", exc_info=True)
            await runtime.stop()
            raise
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="VibeSensor", lifespan=lifespan)
    app.state.runtime = runtime
    app.include_router(create_router(runtime))
    if os.getenv("VIBESENSOR_SERVE_STATIC", "1") == "1":
        # Prefer packaged static assets (baked into the wheel by CI), then
        # fall back to the legacy ``apps/server/public/`` directory used by
        # Docker builds and local development.
        packaged_static = _PACKAGE_DIR / "static"
        legacy_public = SERVER_DIR / "public"
        if (packaged_static / "index.html").exists():
            static_dir = packaged_static
        elif (legacy_public / "index.html").exists():
            static_dir = legacy_public
        else:
            message = (
                "UI not built. Run tools/sync_ui_to_pi_public.py, "
                "build the Docker image, or install a release wheel."
            )
            LOGGER.error(
                "%s Missing index.html in %s and %s",
                message,
                packaged_static,
                legacy_public,
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
