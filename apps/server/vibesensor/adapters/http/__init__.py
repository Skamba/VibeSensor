"""HTTP adapter package."""

from __future__ import annotations

from typing import Any

__all__ = ["create_router"]


def __getattr__(name: str) -> Any:
    if name == "create_router":
        from .routes import create_router

        return create_router
    raise AttributeError(name)
