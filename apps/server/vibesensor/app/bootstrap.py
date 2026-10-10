"""FastAPI application factory.

Service construction lives in ``composition.py``. This module creates the
FastAPI app, wires the lifespan, and serves static assets. The Granian worker
process imports it; the ``vibesensor-server`` supervisor process does not
(see ``serve.py``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from vibesensor.app.composition import build_runtime
from vibesensor.app.config_loader import load_config
from vibesensor.app.lifecycle import LifecycleManager
from vibesensor.common.process_settings import (
    CONFIG_PATH_ENV,
    load_bootstrap_env_settings,
)
from vibesensor.common.structured_logging import configure_logging
from vibesensor.ingest.udp_data_rx import start_udp_data_receiver
from vibesensor.web.error_boundary import install_http_exception_handlers
from vibesensor.web.middleware import (
    install_captive_portal_middleware,
    install_local_mutation_safety_middleware,
    install_request_logging_middleware,
)
from vibesensor.web.router import create_router

__all__ = ["create_app", "create_app_from_env"]

LOGGER = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent.parent
"""Resolved directory containing this package, cached at import time to avoid
repeated filesystem resolution in ``create_app()``."""

_CONFIG_PATH_ENV = CONFIG_PATH_ENV


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the VibeSensor FastAPI application."""
    configure_logging(None)
    config = load_config(config_path)
    bootstrap_settings = load_bootstrap_env_settings()
    configure_logging(config.logging.app_log_path)
    runtime = build_runtime(config)
    lifecycle = LifecycleManager(
        runtime=runtime.lifecycle,
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

    app = FastAPI(title="VibeSensor", lifespan=lifespan)
    app.state.runtime = runtime
    install_http_exception_handlers(app)
    install_local_mutation_safety_middleware(app)
    install_captive_portal_middleware(app)
    install_request_logging_middleware(app)
    app.include_router(create_router(runtime.web))
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
