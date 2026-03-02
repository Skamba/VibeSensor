"""Sensor event detection — parse incoming spectra payloads into discrete events."""

from __future__ import annotations

import logging
from time import monotonic
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
    client_map = {
        str(client.get("id")): str(client.get("name") or client.get("id") or "")
        for client in clients
        if isinstance(client, dict)
    }
    client_location_map = {
        str(client.get("id")): str(client.get("location") or "")
        for client in clients
        if isinstance(client, dict)
    }
    clients_payload = spectra.get("clients")
    if not isinstance(clients_payload, dict):
        return []

    settings_bundle = build_diagnostic_settings(settings)
    entries: list[tuple[str, str, str, list[dict[str, Any]]]] = []
    for client_id, payload in clients_payload.items():
        if not isinstance(payload, dict):
            continue
        strength_metrics = payload.get("strength_metrics")
        if not isinstance(strength_metrics, dict):
            LOGGER.debug("Skipping client %s: missing strength_metrics", client_id)
            continue
        peaks_raw = strength_metrics.get("top_peaks")
        if not isinstance(peaks_raw, list):
            LOGGER.debug("Skipping client %s: missing top_peaks", client_id)
            continue
        label = client_map.get(str(client_id), str(client_id))
        location = client_location_map.get(str(client_id), "")
        entries.append((str(client_id), label, location, peaks_raw))

    now_ms = int(monotonic() * 1000.0)
    events: list[_RecentEvent] = []
    for client_id, label, location, peaks_raw in entries:
        for peak in peaks_raw[:4]:
            if not isinstance(peak, dict):
                continue
            try:
                peak_hz = float(peak.get("hz"))
                peak_amp = float(peak.get("amp"))
                vibration_strength_db = float(peak.get("vibration_strength_db"))
            except (TypeError, ValueError) as exc:
                LOGGER.debug("Skipping invalid peak for %s: %s", client_id, exc)
                continue
            classification = classify_peak_hz(
                peak_hz=peak_hz,
                speed_mps=speed_mps,
                settings=settings_bundle,
            )
            events.append(
                _RecentEvent(
                    ts_ms=now_ms,
                    sensor_id=client_id,
                    sensor_label=label,
                    sensor_location=location,
                    peak_hz=peak_hz,
                    peak_amp=float(peak_amp),
                    vibration_strength_db=float(vibration_strength_db),
                    class_key=str(classification["key"]),
                )
            )
    return events
