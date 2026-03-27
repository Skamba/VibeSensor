"""Cross-cutting shared helpers and protocol-style ports used across the server."""

from __future__ import annotations

__all__ = [
    "ClientTracker",
    "ResolvedSpeedSnapshot",
    "RunPersistence",
    "SettingsReader",
    "SignalSource",
    "SpeedProvider",
    "TrackedClient",
]


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(name)

    from vibesensor.shared import ports

    return getattr(ports, name)
