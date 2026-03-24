"""WsBroadcastService – WebSocket payload assembly with per-tick caching.

Scope boundary: this module owns **live telemetry transport only**.  It
broadcasts raw sensor connectivity, GPS speed, FFT spectra, and
mechanically-derived rotational speeds.  It does not carry diagnostic
conclusions (findings, confidence, vibration sources, suitability) —
those are produced by the post-run analysis pipeline and flow through
``metrics_log/post_analysis`` and ``history_db`` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.infra.runtime.client_snapshot import snapshot_for_api
from vibesensor.infra.runtime.processing_loop import STALE_DATA_AGE_S
from vibesensor.infra.runtime.rotational_speeds import (
    build_rotational_speeds_payload,
    rotational_basis_speed_source,
)
from vibesensor.shared.ports import SettingsReader, SpeedProvider, SpeedSourceSettingsReader

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry

from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.payload_types import SCHEMA_VERSION, LiveWsPayload, SpectraPayload


class WsBroadcastService:
    """WebSocket payload assembly: tick management and cached payload building."""

    __slots__ = (
        "_gps_enabled",
        "_gps_monitor",
        "_processor",
        "_registry",
        "_settings_reader",
        "_speed_source_reader",
        "_ui_heavy_push_hz",
        "_ui_push_hz",
        "include_heavy",
        "tick",
        "_shared_payload",
        "_shared_payload_tick",
        "_shared_payload_heavy",
    )

    def __init__(
        self,
        *,
        ui_push_hz: int,
        ui_heavy_push_hz: int,
        registry: ClientRegistry,
        processor: SignalProcessor,
        gps_monitor: SpeedProvider,
        gps_enabled: bool,
        settings_reader: SettingsReader,
        speed_source_reader: SpeedSourceSettingsReader,
    ) -> None:
        self.tick = 0
        self.include_heavy = True
        self._shared_payload: LiveWsPayload | None = None
        self._shared_payload_tick: int = -1
        self._shared_payload_heavy: bool = True
        self._gps_enabled = gps_enabled
        self._ui_push_hz = ui_push_hz
        self._ui_heavy_push_hz = ui_heavy_push_hz
        self._registry = registry
        self._processor = processor
        self._gps_monitor = gps_monitor
        self._settings_reader = settings_reader
        self._speed_source_reader = speed_source_reader

    def on_tick(self) -> None:
        """Advance the broadcast tick counter and toggle heavy-tick flag."""
        heavy_every = max(
            1,
            int(self._ui_push_hz / max(1, self._ui_heavy_push_hz)),
        )
        self.tick += 1
        self.include_heavy = (self.tick % heavy_every) == 0

    def _build_shared_payload(self) -> LiveWsPayload:
        clients = snapshot_for_api(self._registry, include_metrics=False)
        client_ids = [c["id"] for c in clients]
        fresh_ids = self._processor.clients_with_recent_data(
            client_ids,
            max_age_s=STALE_DATA_AGE_S,
        )

        resolution = self._gps_monitor.resolve_speed()
        speed_mps = resolution.speed_mps
        payload: LiveWsPayload = {
            "schema_version": SCHEMA_VERSION,
            "server_time": utc_now_iso(),
            "speed_mps": speed_mps,
            "clients": clients,
            "selected_client_id": None,
            "rotational_speeds": None,
        }
        analysis_settings_snapshot = self._settings_reader.analysis_settings_snapshot()
        speed_source = self._speed_source_reader.get_speed_source()
        basis = rotational_basis_speed_source(
            str(speed_source.get("speedSource") or "gps"),
            gps_enabled=self._gps_enabled,
            resolution_source=resolution.source,
        )
        payload["rotational_speeds"] = build_rotational_speeds_payload(
            basis_speed_source=basis,
            speed_mps=speed_mps,
            analysis_settings=analysis_settings_snapshot,
        )
        spectra: SpectraPayload | None = None
        if self.include_heavy:
            spectra = self._processor.multi_spectrum_payload(fresh_ids)
            payload["spectra"] = spectra
        return payload

    def _refresh_shared_payload(self) -> LiveWsPayload:
        cache_valid = (
            self._shared_payload is not None
            and self._shared_payload_tick == self.tick
            and self._shared_payload_heavy == self.include_heavy
        )
        if cache_valid:
            assert self._shared_payload is not None, (
                "shared payload cache must be populated when cache_valid is True"
            )
            return self._shared_payload
        payload = self._build_shared_payload()
        self._shared_payload = payload
        self._shared_payload_tick = self.tick
        self._shared_payload_heavy = self.include_heavy
        return payload

    def build_payload(self, selected_client: str | None) -> LiveWsPayload:
        """Assemble a full WebSocket broadcast payload."""
        payload = self._refresh_shared_payload()
        clients = payload["clients"]
        active = selected_client
        if active is None and clients:
            active = clients[0]["id"]
        return {
            **payload,
            "selected_client_id": active,
        }
