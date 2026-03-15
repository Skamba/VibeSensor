"""UDP adapter package."""

from __future__ import annotations

from typing import Any

__all__ = ["UDPControlPlane", "UDPDataReceiver"]


def __getattr__(name: str) -> Any:
    if name == "UDPControlPlane":
        from .control_tx import UDPControlPlane

        return UDPControlPlane
    if name == "UDPDataReceiver":
        from .data_rx import UDPDataReceiver

        return UDPDataReceiver
    raise AttributeError(name)
