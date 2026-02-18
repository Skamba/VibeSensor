from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

from .constants import SILENCE_DB
from .diagnostics_shared import (
    build_diagnostic_settings,
    classify_peak_hz,
    severity_from_peak,
    source_keys_from_class_key,
)
from .report_analysis import build_findings_for_samples
from .strength_bands import BANDS, band_rank

SOURCE_KEYS = ("engine", "driveshaft", "wheel", "other")
SEVERITY_KEYS = ("l5", "l4", "l3", "l2", "l1")
LOGGER = logging.getLogger(__name__)


def _new_matrix() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        source: {
            severity: {"count": 0, "seconds": 0.0, "contributors": {}} for severity in SEVERITY_KEYS
        }
        for source in SOURCE_KEYS
    }


def _copy_matrix(
    matrix: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        source: {
            severity: {
                "count": int(cell.get("count", 0)),
                "seconds": float(cell.get("seconds", 0.0)),
                "contributors": dict(cell.get("contributors", {})),
            }
            for severity, cell in columns.items()
        }
        for source, columns in matrix.items()
    }


def _interpolate_to_target(
    source_freq: list[float], source_vals: list[float], desired_freq: list[float]
) -> list[float]:
    if not source_freq or not source_vals:
        return []
    if not desired_freq:
        return source_vals[:]
    if len(source_freq) != len(source_vals) or len(source_freq) < 2:
        return []

    out: list[float] = []
    j = 0
    for freq in desired_freq:
        while j + 1 < len(source_freq) and source_freq[j + 1] < freq:
            j += 1
        if j + 1 >= len(source_freq):
            out.append(source_vals[-1])
            continue
        f0 = source_freq[j]
        f1 = source_freq[j + 1]
        v0 = source_vals[j]
        v1 = source_vals[j + 1]
        if f1 <= f0:
            out.append(v0)
            continue
        ratio = (freq - f0) / (f1 - f0)
        out.append(v0 + ((v1 - v0) * ratio))
    return out


@dataclass(slots=True)
class _RecentEvent:
    ts_ms: int
    sensor_id: str
    sensor_label: str
    peak_hz: float
    peak_amp: float
    vibration_strength_db: float
    class_key: str


@dataclass(slots=True)
class _TrackerLevelState:
    last_strength_db: float = SILENCE_DB
    last_band_rms_g: float = 0.0
    current_bucket_key: str | None = None
    last_update_ms: int = 0
    last_peak_hz: float = 0.0
    last_class_key: str = "other"
    last_sensor_label: str = ""
    last_emitted_ms: int = 0
    severity_state: dict[str, Any] | None = None


class LiveDiagnosticsEngine:
    def __init__(self) -> None:
        self._matrix = _new_matrix()
        self._sensor_trackers: dict[str, _TrackerLevelState] = {}
        self._combined_trackers: dict[str, _TrackerLevelState] = {}
        self._multi_sync_window_ms = 800
        self._multi_freq_bin_hz = 1.5
        self._heartbeat_emit_ms = 3000
        self._latest_events: list[dict[str, Any]] = []
        self._latest_findings: list[dict[str, Any]] = []
        self._active_levels_by_source: dict[str, dict[str, Any]] = {}
        self._active_levels_by_sensor: dict[str, dict[str, Any]] = {}
        self._last_update_ts_ms: int | None = None
        self._last_error: str | None = None

    def reset(self) -> None:
        self._matrix = _new_matrix()
        self._sensor_trackers = {}
        self._combined_trackers = {}
        self._latest_events = []
        self._latest_findings = []
        self._active_levels_by_source = {}
        self._active_levels_by_sensor = {}
        self._last_update_ts_ms = None
        self._last_error = None

    def _update_matrix(self, source_key: str, severity_key: str, contributor_label: str) -> None:
        if source_key not in self._matrix:
            return
        cell = self._matrix[source_key].get(severity_key)
        if cell is None:
            return
        cell["count"] = int(cell["count"]) + 1
        contributors = cell["contributors"]
        contributors[contributor_label] = int(contributors.get(contributor_label, 0)) + 1

    def _accumulate_matrix_seconds(self, dt_seconds: float) -> None:
        if dt_seconds <= 0:
            return
        for source_key, level in self._active_levels_by_source.items():
            bucket = str(level.get("bucket_key") or "")
            if not bucket:
                continue
            cell = self._matrix.get(source_key, {}).get(bucket)
            if cell is None:
                continue
            cell["seconds"] = float(cell.get("seconds", 0.0)) + dt_seconds

    def _update_matrix_many(
        self, source_keys: tuple[str, ...], severity_key: str, contributor_label: str
    ) -> None:
        for source_key in source_keys:
            self._update_matrix(source_key, severity_key, contributor_label)

    def _should_emit_event(
        self,
        *,
        tracker: _TrackerLevelState,
        previous_bucket: str | None,
        current_bucket: str | None,
        now_ms: int,
    ) -> bool:
        if current_bucket is None:
            return False
        prev_rank = band_rank(previous_bucket or "")
        cur_rank = band_rank(current_bucket)
        if previous_bucket is None or cur_rank > prev_rank:
            return True
        return now_ms - tracker.last_emitted_ms >= self._heartbeat_emit_ms

    def _matrix_transition_bucket(
        self, previous_bucket: str | None, current_bucket: str | None
    ) -> str | None:
        if current_bucket is None:
            return None
        if previous_bucket is None:
            return current_bucket
        if band_rank(current_bucket) > band_rank(previous_bucket):
            return current_bucket
        return None

    @staticmethod
    def _apply_severity_to_tracker(
        tracker: _TrackerLevelState,
        vibration_strength_db: float,
        sensor_count: int,
        fallback_db: float | None = None,
    ) -> str | None:
        """Apply severity_from_peak to a tracker, updating its state in-place.

        Returns the previous bucket key so callers can detect transitions.
        """
        previous_bucket = tracker.current_bucket_key
        severity = severity_from_peak(
            vibration_strength_db=vibration_strength_db,
            sensor_count=sensor_count,
            prior_state=tracker.severity_state,
        )
        tracker.severity_state = dict((severity or {}).get("state") or tracker.severity_state or {})
        tracker.current_bucket_key = (
            str(severity["key"]) if severity and severity.get("key") else None
        )
        tracker.last_strength_db = float(
            (severity or {}).get("db")
            or (fallback_db if fallback_db is not None else vibration_strength_db)
        )
        return previous_bucket

    def _upsert_active_level(
        self,
        *,
        active_by_source: dict[str, dict[str, Any]],
        source_keys: tuple[str, ...],
        bucket_key: str,
        strength_db: float,
        sensor_label: str,
        class_key: str,
        peak_hz: float,
    ) -> None:
        for source_key in source_keys:
            existing = active_by_source.get(source_key)
            if existing is None or strength_db > float(existing.get("strength_db", -1e9)):
                active_by_source[source_key] = {
                    "bucket_key": bucket_key,
                    "strength_db": strength_db,
                    "sensor_label": sensor_label,
                    "class_key": class_key,
                    "peak_hz": peak_hz,
                }

    def snapshot(self) -> dict[str, Any]:
        top_finding: dict[str, Any] | None = None
        for finding in self._latest_findings:
            finding_id = str(finding.get("finding_id") or "")
            if finding_id.startswith("REF") or finding_id.startswith("INFO_"):
                continue
            top_finding = finding
            break
        if top_finding is None and self._latest_findings:
            top_finding = self._latest_findings[0]
        return {
            "matrix": _copy_matrix(self._matrix),
            "events": list(self._latest_events),
            "strength_bands": list(BANDS),
            "levels": {
                "by_source": {
                    key: dict(value) for key, value in self._active_levels_by_source.items()
                },
                "by_sensor": {
                    key: dict(value) for key, value in self._active_levels_by_sensor.items()
                },
            },
            "findings": list(self._latest_findings),
            "top_finding": top_finding,
            "error": self._last_error,
        }

    def update(
        self,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any] | None,
        settings: dict[str, float] | None,
        finding_metadata: dict[str, Any] | None = None,
        finding_samples: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if finding_metadata is not None and finding_samples is not None:
            try:
                self._latest_findings = build_findings_for_samples(
                    metadata=finding_metadata,
                    samples=finding_samples,
                    lang="en",
                )
            except ValueError as exc:
                LOGGER.warning("Live diagnostics findings unavailable: %s", exc)
                self._latest_findings = []

        if spectra is None:
            self._last_error = None
            return self.snapshot()

        now_ms = int(monotonic() * 1000.0)
        dt_seconds = 0.0
        if self._last_update_ts_ms is not None:
            dt_seconds = max(0.0, min(1.0, (now_ms - self._last_update_ts_ms) / 1000.0))
        self._last_update_ts_ms = now_ms
        self._accumulate_matrix_seconds(dt_seconds)

        try:
            sensor_events = self._detect_sensor_events(
                speed_mps=speed_mps,
                clients=clients,
                spectra=spectra,
                settings=settings or {},
            )
            self._last_error = None
        except ValueError as exc:
            LOGGER.warning(
                "Live diagnostics update skipped due to invalid spectra payload: %s",
                exc,
            )
            self._last_error = str(exc)
            sensor_events = []
        # Keep continuous tracker state updated every tick, and only throttle log emission.
        emitted_events: list[dict[str, Any]] = []
        active_by_source: dict[str, dict[str, Any]] = {}
        active_by_sensor: dict[str, dict[str, Any]] = {}

        latest_by_tracker: dict[str, _RecentEvent] = {}
        for event in sensor_events:
            tracker_key = f"{event.sensor_id}:{event.class_key}"
            previous = latest_by_tracker.get(tracker_key)
            if previous is None or event.vibration_strength_db > previous.vibration_strength_db:
                latest_by_tracker[tracker_key] = event

        for tracker_key, event in latest_by_tracker.items():
            tracker = self._sensor_trackers.get(tracker_key) or _TrackerLevelState()
            previous_bucket = self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=event.vibration_strength_db,
                sensor_count=1,
            )
            tracker.last_band_rms_g = float(event.peak_amp)
            tracker.last_update_ms = now_ms
            tracker.last_peak_hz = float(event.peak_hz)
            tracker.last_class_key = event.class_key
            tracker.last_sensor_label = event.sensor_label
            self._sensor_trackers[tracker_key] = tracker

            if tracker.current_bucket_key:
                source_keys = source_keys_from_class_key(event.class_key)
                self._upsert_active_level(
                    active_by_source=active_by_source,
                    source_keys=source_keys,
                    bucket_key=tracker.current_bucket_key,
                    strength_db=tracker.last_strength_db,
                    sensor_label=event.sensor_label,
                    class_key=event.class_key,
                    peak_hz=event.peak_hz,
                )
                sensor_existing = active_by_sensor.get(event.sensor_id)
                if sensor_existing is None or tracker.last_strength_db > float(
                    sensor_existing.get("strength_db", -1e9)
                ):
                    active_by_sensor[event.sensor_id] = {
                        "bucket_key": tracker.current_bucket_key,
                        "strength_db": tracker.last_strength_db,
                        "class_key": event.class_key,
                        "peak_hz": event.peak_hz,
                    }

            transition_bucket = self._matrix_transition_bucket(
                previous_bucket, tracker.current_bucket_key
            )
            if transition_bucket:
                source_keys = source_keys_from_class_key(event.class_key)
                self._update_matrix_many(source_keys, transition_bucket, event.sensor_label)

            if self._should_emit_event(
                tracker=tracker,
                previous_bucket=previous_bucket,
                current_bucket=tracker.current_bucket_key,
                now_ms=now_ms,
            ):
                tracker.last_emitted_ms = now_ms
                emitted_events.append(
                    {
                        "kind": "single",
                        "class_key": event.class_key,
                        "sensor_count": 1,
                        "sensor_id": event.sensor_id,
                        "sensor_label": event.sensor_label,
                        "sensor_labels": [event.sensor_label],
                        "peak_hz": event.peak_hz,
                        "peak_amp": event.peak_amp,
                        "severity_key": tracker.current_bucket_key,
                        "vibration_strength_db": tracker.last_strength_db,
                    }
                )

        seen_tracker_keys = set(latest_by_tracker)
        for tracker_key, tracker in list(self._sensor_trackers.items()):
            if tracker_key in seen_tracker_keys:
                continue
            self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=SILENCE_DB,
                sensor_count=1,
                fallback_db=SILENCE_DB,
            )

        # Source/sensor active levels come from continuous tracker state (not emitted events).
        for tracker_key, tracker in self._sensor_trackers.items():
            if tracker.current_bucket_key is None:
                continue
            sensor_id, _, class_key = tracker_key.partition(":")
            source_keys = source_keys_from_class_key(class_key or tracker.last_class_key)
            self._upsert_active_level(
                active_by_source=active_by_source,
                source_keys=source_keys,
                bucket_key=tracker.current_bucket_key,
                strength_db=tracker.last_strength_db,
                sensor_label=tracker.last_sensor_label,
                class_key=class_key or tracker.last_class_key,
                peak_hz=tracker.last_peak_hz,
            )
            sensor_existing = active_by_sensor.get(sensor_id)
            if sensor_existing is None or tracker.last_strength_db > float(
                sensor_existing.get("strength_db", -1e9)
            ):
                active_by_sensor[sensor_id] = {
                    "bucket_key": tracker.current_bucket_key,
                    "strength_db": tracker.last_strength_db,
                    "class_key": class_key or tracker.last_class_key,
                    "peak_hz": tracker.last_peak_hz,
                }

        # Build combined groups from fresh per-sensor continuous tracker state.
        fresh_sensor_trackers: list[_TrackerLevelState] = []
        for tracker in self._sensor_trackers.values():
            if tracker.current_bucket_key is None:
                continue
            if now_ms - tracker.last_update_ms > self._multi_sync_window_ms:
                continue
            fresh_sensor_trackers.append(tracker)

        by_class: dict[str, list[_TrackerLevelState]] = {}
        for tracker in fresh_sensor_trackers:
            by_class.setdefault(tracker.last_class_key, []).append(tracker)

        seen_combined_keys: set[str] = set()
        for class_key, trackers in by_class.items():
            trackers.sort(key=lambda item: item.last_peak_hz)
            groups: list[list[_TrackerLevelState]] = []
            for tracker in trackers:
                if not groups:
                    groups.append([tracker])
                    continue
                prev = groups[-1][-1]
                if abs(prev.last_peak_hz - tracker.last_peak_hz) <= self._multi_freq_bin_hz:
                    groups[-1].append(tracker)
                else:
                    groups.append([tracker])

            for group in groups:
                if len(group) < 2:
                    continue
                avg_hz = sum(item.last_peak_hz for item in group) / len(group)
                avg_amp = sum(item.last_band_rms_g for item in group) / len(group)
                avg_strength = sum(item.last_strength_db for item in group) / len(group)
                freq_bin = round(avg_hz / self._multi_freq_bin_hz)
                combined_key = f"combined:{class_key}:{freq_bin}"
                seen_combined_keys.add(combined_key)
                tracker = self._combined_trackers.get(combined_key) or _TrackerLevelState(
                    last_class_key=class_key
                )
                previous_bucket = self._apply_severity_to_tracker(
                    tracker,
                    vibration_strength_db=avg_strength,
                    sensor_count=len(group),
                )
                tracker.last_band_rms_g = avg_amp
                tracker.last_update_ms = now_ms
                tracker.last_peak_hz = avg_hz
                tracker.last_class_key = class_key
                tracker.last_sensor_label = (
                    f"combined({', '.join(item.last_sensor_label for item in group)})"
                )
                self._combined_trackers[combined_key] = tracker

                if tracker.current_bucket_key:
                    source_keys = source_keys_from_class_key(class_key)
                    self._upsert_active_level(
                        active_by_source=active_by_source,
                        source_keys=source_keys,
                        bucket_key=tracker.current_bucket_key,
                        strength_db=tracker.last_strength_db,
                        sensor_label=tracker.last_sensor_label,
                        class_key=class_key,
                        peak_hz=avg_hz,
                    )

                transition_bucket = self._matrix_transition_bucket(
                    previous_bucket, tracker.current_bucket_key
                )
                if transition_bucket:
                    source_keys = source_keys_from_class_key(class_key)
                    self._update_matrix_many(
                        source_keys, transition_bucket, tracker.last_sensor_label
                    )

                if self._should_emit_event(
                    tracker=tracker,
                    previous_bucket=previous_bucket,
                    current_bucket=tracker.current_bucket_key,
                    now_ms=now_ms,
                ):
                    tracker.last_emitted_ms = now_ms
                    emitted_events.append(
                        {
                            "kind": "multi",
                            "class_key": class_key,
                            "sensor_count": len(group),
                            "sensor_labels": [item.last_sensor_label for item in group],
                            "peak_hz": avg_hz,
                            "peak_amp": avg_amp,
                            "severity_key": tracker.current_bucket_key,
                            "vibration_strength_db": tracker.last_strength_db,
                        }
                    )

        for combined_key, tracker in list(self._combined_trackers.items()):
            if combined_key in seen_combined_keys:
                continue
            self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=SILENCE_DB,
                sensor_count=2,
                fallback_db=SILENCE_DB,
            )

        self._active_levels_by_source = active_by_source
        self._active_levels_by_sensor = active_by_sensor
        self._latest_events = emitted_events
        return self.snapshot()

    def _detect_sensor_events(
        self,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any],
        settings: dict[str, float],
    ) -> list[_RecentEvent]:
        client_map = {
            str(client.get("id")): str(client.get("name") or client.get("id") or "")
            for client in clients
            if isinstance(client, dict)
        }
        clients_payload = spectra.get("clients")
        if not isinstance(clients_payload, dict):
            return []

        settings_bundle = build_diagnostic_settings(settings)
        entries: list[tuple[str, str, list[dict[str, Any]]]] = []
        for client_id, payload in clients_payload.items():
            if not isinstance(payload, dict):
                continue
            strength_metrics = payload.get("strength_metrics")
            if not isinstance(strength_metrics, dict):
                raise ValueError("Missing required strength_metrics payload for live diagnostics.")
            peaks_raw = strength_metrics.get("top_peaks")
            if not isinstance(peaks_raw, list):
                raise ValueError("Missing top_peaks in strength_metrics payload.")
            label = client_map.get(str(client_id), str(client_id))
            entries.append((str(client_id), label, peaks_raw))

        now_ms = int(monotonic() * 1000.0)
        events: list[_RecentEvent] = []
        for client_id, label, peaks_raw in entries:
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
                        peak_hz=peak_hz,
                        peak_amp=float(peak_amp),
                        vibration_strength_db=float(vibration_strength_db),
                        class_key=str(classification["key"]),
                    )
                )
        return events
