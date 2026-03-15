"""Runtime package – runtime coordination."""

from __future__ import annotations

from typing import Any

__all__ = ["ProcessingLoopState", "RuntimeHealthState", "RuntimeState"]


def __getattr__(name: str) -> Any:
    if name == "RuntimeHealthState":
        from .health_state import RuntimeHealthState

        return RuntimeHealthState
    if name == "ProcessingLoopState":
        from .processing_loop import ProcessingLoopState

        return ProcessingLoopState
    if name == "RuntimeState":
        from .state import RuntimeState

        return RuntimeState
    raise AttributeError(name)
