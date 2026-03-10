"""WsBroadcastService – WebSocket payload assembly with per-tick caching.

Owns:
- ``WsBroadcastCache`` dataclass (tick counter + per-tick result caches)
- ``WsBroadcastService`` (payload assembly + tick management)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .processing_loop import STALE_DATA_AGE_S
from .rotational_speeds import (
    build_rotational_speeds_payload,
    rotational_basis_speed_source,
)

if TYPE_CHECKING:
    from .state import (
        RuntimeIngressSubsystem,
        RuntimeSettingsSubsystem,
    )

from ..payload_types import SCHEMA_VERSION, LiveWsPayload, SpectraPayload
from ..runlog import utc_now_iso


@dataclass(slots=True)
class WsBroadcastCache:
    """Tick counter and per-tick caches for WebSocket payload assembly."""

    tick: int = 0
    include_heavy: bool = True
    shared_payload: LiveWsPayload | None = None
    shared_payload_tick: int = -1
    shared_payload_heavy: bool = True

    def advance(self, heavy_every: int) -> None:
        """Advance the tick counter and update ``include_heavy``."""
        self.tick += 1
        self.include_heavy = (self.tick % heavy_every) == 0


class WsBroadcastService:
    """WebSocket payload assembly: tick management and cached payload building."""

    __slots__ = (
        "_ingress",
        "_settings",
        "_ui_heavy_push_hz",
        "_ui_push_hz",
        "cache",
    )

    def __init__(
        self,
        *,
        cache: WsBroadcastCache,
        ui_push_hz: int,
        ui_heavy_push_hz: int,
        ingress: RuntimeIngressSubsystem,
        settings: RuntimeSettingsSubsystem,
    ) -> None:
        self.cache = cache
        self._ui_push_hz = ui_push_hz
        self._ui_heavy_push_hz = ui_heavy_push_hz
        self._ingress = ingress
        self._settings = settings

    def on_tick(self) -> None:
        """Advance the broadcast tick counter and toggle heavy-tick flag."""
        heavy_every = max(
            1,
            int(self._ui_push_hz / max(1, self._ui_heavy_push_hz)),
        )
        self.cache.advance(heavy_every)

    def _build_shared_payload(self) -> LiveWsPayload:
        active_ids = self._ingress.registry.active_client_ids()
        metrics_by_client = self._ingress.processor.all_latest_metrics(active_ids)
        clients = self._ingress.registry.snapshot_for_api(
            metrics_by_client=metrics_by_client,
        )
        client_ids = [c["id"] for c in clients]
        fresh_ids = self._ingress.processor.clients_with_recent_data(
            client_ids,
            max_age_s=STALE_DATA_AGE_S,
        )

        resolution = self._settings.gps_monitor.resolve_speed()
        speed_mps = resolution.speed_mps
        payload: LiveWsPayload = {
            "schema_version": SCHEMA_VERSION,
            "server_time": utc_now_iso(),
            "speed_mps": speed_mps,
            "clients": clients,
        }
        analysis_settings_snapshot = self._settings.analysis_settings.snapshot()
        basis = rotational_basis_speed_source(
            self._settings.settings_store,
            self._settings.gps_monitor,
            resolution_source=resolution.source,
        )
        payload["rotational_speeds"] = build_rotational_speeds_payload(
            basis_speed_source=basis,
            speed_mps=speed_mps,
            analysis_settings=analysis_settings_snapshot,
        )
        spectra: SpectraPayload | None = None
        if self.cache.include_heavy:
            spectra = self._ingress.processor.multi_spectrum_payload(fresh_ids)
            payload["spectra"] = spectra
        return payload

    def _refresh_shared_payload(self) -> LiveWsPayload:
        cache_valid = (
            self.cache.shared_payload is not None
            and self.cache.shared_payload_tick == self.cache.tick
            and self.cache.shared_payload_heavy == self.cache.include_heavy
        )
        if cache_valid:
            assert self.cache.shared_payload is not None, (
                "shared payload cache must be populated when cache_valid is True"
            )
            return self.cache.shared_payload
        payload = self._build_shared_payload()
        self.cache.shared_payload = payload
        self.cache.shared_payload_tick = self.cache.tick
        self.cache.shared_payload_heavy = self.cache.include_heavy
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
