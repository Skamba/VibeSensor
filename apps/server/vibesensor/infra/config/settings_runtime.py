"""Runtime settings application helpers extracted from SettingsStore."""

from __future__ import annotations

from vibesensor.shared.ports import SpeedSourceSettingsReader, SpeedSourceSync

__all__ = ["SettingsRuntimeApplier"]


class SettingsRuntimeApplier:
    """Apply current persisted settings into long-lived runtime collaborators."""

    __slots__ = ("_gps_monitor", "_speed_source_reader")

    def __init__(
        self,
        *,
        gps_monitor: SpeedSourceSync | None,
        speed_source_reader: SpeedSourceSettingsReader,
    ) -> None:
        self._gps_monitor = gps_monitor
        self._speed_source_reader = speed_source_reader

    def apply_speed_source(self) -> None:
        """Push the current speed-source config into the GPS/runtime layer."""
        if self._gps_monitor is None:
            return
        speed_source = self._speed_source_reader.speed_source()
        raw = self._speed_source_reader.get_speed_source()
        self._gps_monitor.apply_speed_source_settings(
            effective_speed_kmh=speed_source.effective_speed_kmh,
            manual_source_selected=speed_source.is_manual,
            stale_timeout_s=raw.get("staleTimeoutS"),
        )

    def sync_all(self) -> None:
        """Apply all runtime-facing settings at startup."""
        self.apply_speed_source()
