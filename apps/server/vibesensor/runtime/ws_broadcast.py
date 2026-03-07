"""WsBroadcastService – WebSocket payload assembly with per-tick caching.

Owns:
- ``WsBroadcastCache`` dataclass (tick counter + per-tick result caches)
- ``WsBroadcastService`` (payload assembly + tick management)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from .processing_loop import STALE_DATA_AGE_S
from .rotational_speeds import (
    build_rotational_speeds_payload,
    rotational_basis_speed_source,
)

if TYPE_CHECKING:
    from ..live_diagnostics.engine import LiveDiagnosticsEngine
    from ..metrics_log import MetricsLogger
    from .subsystems import (
        RuntimeDiagnosticsSubsystem,
        RuntimeIngressSubsystem,
        RuntimeSettingsSubsystem,
    )

from ..runlog import utc_now_iso
from ..ws_models import SCHEMA_VERSION


@dataclass(slots=True)
class WsBroadcastCache:
    """Tick counter and per-tick caches for WebSocket payload assembly."""

    tick: int = 0
    include_heavy: bool = True
    analysis_metadata: dict[str, object] | None = None
    analysis_samples: list[dict[str, object]] = field(default_factory=list)
    analysis_tick: int = -1
    diagnostics: dict[str, object] | None = None
    diagnostics_tick: int = -1
    diagnostics_heavy: bool = True

    def advance(self, heavy_every: int) -> None:
        """Advance the tick counter and update ``include_heavy``."""
        self.tick += 1
        self.include_heavy = (self.tick % heavy_every) == 0

    def refresh_analysis(
        self,
        metrics_logger: MetricsLogger,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Return (metadata, samples), refreshing only when the cache is stale."""
        need_refresh = self.analysis_metadata is None or (
            self.include_heavy and self.analysis_tick != self.tick
        )
        if need_refresh:
            metadata, samples = metrics_logger.analysis_snapshot()
            self.analysis_metadata = metadata
            self.analysis_samples = samples
            self.analysis_tick = self.tick
        assert self.analysis_metadata is not None, (
            "analysis cache must be populated: need_refresh was True or cache was valid"
        )
        return self.analysis_metadata, self.analysis_samples

    def refresh_diagnostics(
        self,
        live_diagnostics: LiveDiagnosticsEngine,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any] | None,
        settings: dict[str, Any],
        analysis_metadata: dict[str, object],
        analysis_samples: list[dict[str, object]],
        language: str,
    ) -> dict[str, object]:
        """Return diagnostics payload, refreshing only when the cache is stale."""
        cache_valid = (
            self.diagnostics is not None
            and self.diagnostics_tick == self.tick
            and self.diagnostics_heavy == self.include_heavy
        )
        if cache_valid:
            assert self.diagnostics is not None, (
                "diagnostics cache must be populated when cache_valid is True"
            )
            return self.diagnostics
        diagnostics = live_diagnostics.update(
            speed_mps=speed_mps,
            clients=clients,
            spectra=spectra,
            settings=settings,
            finding_metadata=analysis_metadata,
            finding_samples=analysis_samples,
            language=language,
        )
        self.diagnostics = cast(dict[str, object], diagnostics)
        self.diagnostics_tick = self.tick
        self.diagnostics_heavy = self.include_heavy
        return self.diagnostics


class WsBroadcastService:
    """WebSocket payload assembly: tick management and cached payload building."""

    __slots__ = (
        "cache",
        "_ui_push_hz",
        "_ui_heavy_push_hz",
        "_ingress",
        "_settings",
        "_diagnostics",
    )

    def __init__(
        self,
        *,
        cache: WsBroadcastCache,
        ui_push_hz: int,
        ui_heavy_push_hz: int,
        ingress: RuntimeIngressSubsystem,
        settings: RuntimeSettingsSubsystem,
        diagnostics: RuntimeDiagnosticsSubsystem,
    ) -> None:
        self.cache = cache
        self._ui_push_hz = ui_push_hz
        self._ui_heavy_push_hz = ui_heavy_push_hz
        self._ingress = ingress
        self._settings = settings
        self._diagnostics = diagnostics

    def on_tick(self) -> None:
        """Advance the broadcast tick counter and toggle heavy-tick flag."""
        heavy_every = max(
            1,
            int(self._ui_push_hz / max(1, self._ui_heavy_push_hz)),
        )
        self.cache.advance(heavy_every)

    def build_payload(self, selected_client: str | None) -> dict[str, Any]:
        """Assemble a full WebSocket broadcast payload."""
        clients = self._ingress.registry.snapshot_for_api()
        active = selected_client
        if active is None and clients:
            active = clients[0]["id"]
        client_ids = [c["id"] for c in clients]
        fresh_ids = self._ingress.processor.clients_with_recent_data(
            client_ids,
            max_age_s=STALE_DATA_AGE_S,
        )

        resolution = self._settings.gps_monitor.resolve_speed()
        speed_mps = resolution.speed_mps
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "server_time": utc_now_iso(),
            "speed_mps": speed_mps,
            "clients": clients,
            "selected_client_id": active,
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
        analysis_metadata, analysis_samples = self.cache.refresh_analysis(
            self._diagnostics.metrics_logger
        )
        if self.cache.include_heavy:
            payload["spectra"] = self._ingress.processor.multi_spectrum_payload(fresh_ids)
        payload["diagnostics"] = self.cache.refresh_diagnostics(
            self._diagnostics.live_diagnostics,
            speed_mps=speed_mps,
            clients=clients,
            spectra=payload.get("spectra") if self.cache.include_heavy else None,
            settings=analysis_settings_snapshot,
            analysis_metadata=analysis_metadata,
            analysis_samples=analysis_samples,
            language=self._settings.settings_store.language,
        )
        return payload
