"""Sensor event detection — parse incoming spectra payloads into discrete events."""

from __future__ import annotations

import logging
from typing import Any

from ..diagnostics_shared import build_diagnostic_settings, classify_peak_hz
from ._types import _RecentEvent

LOGGER = logging.getLogger(__name__)


def detect_sensor_events(
    *,
    speed_mps: float | None,
    clients: list[dict[str, Any]],
    spectra: dict[str, Any],
    settings: dict[str, float],
) -> list[_RecentEvent]:
    """Extract per-sensor vibration events from a WebSocket spectra payload."""
    # Single pass over clients to build both name and location lookups.
    client_map: dict[str, str] = {}
    client_location_map: dict[str, str] = {}
    for client in clients:
        if not isinstance(client, dict):
            continue
        cid = str(client.get("id"))
        client_map[cid] = str(client.get("name") or client.get("id") or "")
        client_location_map[cid] = str(client.get("location") or "")

    clients_payload = spectra.get("clients")
    if not isinstance(clients_payload, dict):
        return []

    settings_bundle = build_diagnostic_settings(settings)
    _classify = classify_peak_hz  # local bind for inner loop
    _debug = LOGGER.debug

    events: list[_RecentEvent] = []
    _append = events.append
    for client_id, payload in clients_payload.items():
        if not isinstance(payload, dict):
            continue
        strength_metrics = payload.get("strength_metrics")
        if not isinstance(strength_metrics, dict):
            _debug("Skipping client %s: missing strength_metrics", client_id)
            continue
        peaks_raw = strength_metrics.get("top_peaks")
        if not isinstance(peaks_raw, list):
            _debug("Skipping client %s: missing top_peaks", client_id)
            continue
        label = client_map.get(client_id, client_id)
        location = client_location_map.get(client_id, "")
        for peak in peaks_raw[:4]:
            if not isinstance(peak, dict):
                continue
            _get = peak.get
            try:
                peak_hz = float(_get("hz"))
                peak_amp = float(_get("amp"))
                vibration_strength_db = float(_get("vibration_strength_db"))
            except (TypeError, ValueError) as exc:
                _debug("Skipping invalid peak for %s: %s", client_id, exc)
                continue
            classification = _classify(
                peak_hz=peak_hz,
                speed_mps=speed_mps,
                settings=settings_bundle,
            )
            _append(
                _RecentEvent(
                    sensor_id=client_id,
                    sensor_label=label,
                    sensor_location=location,
                    peak_hz=peak_hz,
                    peak_amp=peak_amp,
                    vibration_strength_db=vibration_strength_db,
                    class_key=str(classification["key"]),
                )
            )
    return events
