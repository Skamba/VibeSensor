"""WsBroadcastService – WebSocket payload assembly with per-tick caching.

Scope boundary: this module owns **live telemetry transport only**.  It
broadcasts raw sensor connectivity, GPS speed, FFT spectra, and
mechanically-derived rotational speeds.  It does not carry diagnostic
conclusions (findings, confidence, vibration sources, suitability) —
those are produced by the post-run analysis pipeline and flow through
``metrics_log/post_analysis`` and ``history_db`` instead.
"""

from __future__ import annotations

from typing import Protocol

from vibesensor.shared.types.payload_types import LiveWsPayload


class LiveWsPayloadSource(Protocol):
    """Focused shared-payload reader used by the broadcaster transport layer."""

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload: ...


class WsBroadcastService:
    """WebSocket payload assembly: tick management and cached payload building."""

    __slots__ = (
        "_payload_source",
        "_heavy_tick_credit",
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
        payload_source: LiveWsPayloadSource,
    ) -> None:
        self.tick = 0
        self.include_heavy = True
        self._heavy_tick_credit = 0
        self._shared_payload: LiveWsPayload | None = None
        self._shared_payload_tick: int = -1
        self._shared_payload_heavy: bool = True
        self._ui_push_hz = ui_push_hz
        self._ui_heavy_push_hz = ui_heavy_push_hz
        self._payload_source = payload_source

    def on_tick(self) -> None:
        """Advance the broadcast tick counter and toggle heavy-tick flag."""
        push_hz = max(1, self._ui_push_hz)
        heavy_hz = max(1, self._ui_heavy_push_hz)
        self.tick += 1
        if heavy_hz >= push_hz:
            self.include_heavy = True
            self._heavy_tick_credit = 0
            return
        self._heavy_tick_credit += heavy_hz
        self.include_heavy = self._heavy_tick_credit >= push_hz
        if self.include_heavy:
            self._heavy_tick_credit -= push_hz

    def _build_shared_payload(self) -> LiveWsPayload:
        return self._payload_source.build_shared_payload(include_heavy=self.include_heavy)

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
