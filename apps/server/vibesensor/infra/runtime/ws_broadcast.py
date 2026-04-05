"""WsBroadcastService – WebSocket payload assembly with per-tick caching.

Scope boundary: this module owns **live telemetry transport only**.  It
broadcasts raw sensor connectivity, GPS speed, FFT spectra, and
mechanically-derived rotational speeds.  It does not carry diagnostic
conclusions (findings, confidence, vibration sources, suitability) —
those are produced by the post-run analysis pipeline and flow through
``metrics_log/post_analysis`` and ``history_db`` instead.
"""

from __future__ import annotations

from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.shared.types.payload_types import LiveWsPayload


class WsBroadcastService:
    """WebSocket payload assembly: tick management and cached payload building."""

    __slots__ = (
        "_payload_projector",
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
        payload_projector: LiveWsPayloadProjector,
    ) -> None:
        self.tick = 0
        self.include_heavy = True
        self._shared_payload: LiveWsPayload | None = None
        self._shared_payload_tick: int = -1
        self._shared_payload_heavy: bool = True
        self._ui_push_hz = ui_push_hz
        self._ui_heavy_push_hz = ui_heavy_push_hz
        self._payload_projector = payload_projector

    def on_tick(self) -> None:
        """Advance the broadcast tick counter and toggle heavy-tick flag."""
        heavy_every = max(
            1,
            int(self._ui_push_hz / max(1, self._ui_heavy_push_hz)),
        )
        self.tick += 1
        self.include_heavy = (self.tick % heavy_every) == 0

    def _build_shared_payload(self) -> LiveWsPayload:
        return self._payload_projector.build_shared_payload(include_heavy=self.include_heavy)

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
