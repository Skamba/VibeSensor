from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from time import monotonic
from typing import Any

from vibesensor_core.strength_bands import BANDS, band_rank
from vibesensor_core.vibration_strength import vibration_strength_db_scalar

from .constants import MPS_TO_KMH, SILENCE_DB
from .diagnostics_shared import (
    build_diagnostic_settings,
    classify_peak_hz,
    severity_from_peak,
    source_keys_from_class_key,
)
from .report.phase_segmentation import DrivingPhase, _classify_sample_phase
from .report.summary import build_findings_for_samples

SOURCE_KEYS = ("engine", "driveshaft", "wheel", "other")
SEVERITY_KEYS = ("l5", "l4", "l3", "l2", "l1")
LOGGER = logging.getLogger(__name__)

_PHASE_HISTORY_MAX = 5
_MATRIX_WINDOW_MS = 5 * 60 * 1000


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


def _combine_amplitude_strength_db(values_db: list[float]) -> float:
    if not values_db:
        return SILENCE_DB
    linear = [10.0 ** (float(value) / 20.0) for value in values_db]
    mean_linear = sum(linear) / max(1, len(linear))
    if mean_linear <= 0.0:
        return SILENCE_DB
    return vibration_strength_db_scalar(
        peak_band_rms_amp_g=mean_linear,
        floor_amp_g=1.0,
        epsilon_g=1e-9,
    )


@dataclass(slots=True)
class _RecentEvent:
    ts_ms: int
    sensor_id: str
    sensor_label: str
    sensor_location: str
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
    last_sensor_location: str = ""
    last_emitted_ms: int = 0
    severity_state: dict[str, Any] | None = None


@dataclass(slots=True)
class _MatrixCountEvent:
    ts_ms: int
    source_key: str
    severity_key: str
    contributor_label: str


@dataclass(slots=True)
class _MatrixSecondsEvent:
    ts_ms: int
    source_key: str
    severity_key: str
    dt_seconds: float


class LiveDiagnosticsEngine:
    def __init__(self) -> None:
        self._matrix = _new_matrix()
        self._matrix_count_events: deque[_MatrixCountEvent] = deque()
        self._matrix_seconds_events: deque[_MatrixSecondsEvent] = deque()
        self._sensor_trackers: dict[str, _TrackerLevelState] = {}
        self._combined_trackers: dict[str, _TrackerLevelState] = {}
        self._multi_sync_window_ms = 800
        self._multi_freq_bin_hz = 1.5
        self._heartbeat_emit_ms = 3000
        self._latest_events: list[dict[str, Any]] = []
        self._latest_findings: list[dict[str, Any]] = []
        self._active_levels_by_source: dict[str, dict[str, Any]] = {}
        self._active_levels_by_sensor: dict[str, dict[str, Any]] = {}
        self._active_levels_by_location: dict[str, dict[str, Any]] = {}
        self._last_update_ts_ms: int | None = None
        self._last_error: str | None = None
        self._phase_speed_history: list[tuple[float, float | None]] = []
        self._current_phase: str = DrivingPhase.IDLE.value
        self._diagnostics_sequence: int = 0
        self._next_event_id: int = 0

    def reset(self) -> None:
        self._matrix = _new_matrix()
        self._matrix_count_events.clear()
        self._matrix_seconds_events.clear()
        self._sensor_trackers = {}
        self._combined_trackers = {}
        self._latest_events = []
        self._latest_findings = []
        self._active_levels_by_source = {}
        self._active_levels_by_sensor = {}
        self._active_levels_by_location = {}
        self._last_update_ts_ms = None
        self._last_error = None
        self._phase_speed_history = []
        self._current_phase = DrivingPhase.IDLE.value
        self._diagnostics_sequence = 0
        self._next_event_id = 0

    def _record_matrix_count(
        self,
        now_ms: int,
        source_key: str,
        severity_key: str,
        contributor_label: str,
    ) -> None:
        if source_key not in SOURCE_KEYS or severity_key not in SEVERITY_KEYS:
            return
        self._matrix_count_events.append(
            _MatrixCountEvent(
                ts_ms=now_ms,
                source_key=source_key,
                severity_key=severity_key,
                contributor_label=contributor_label,
            )
        )

    def _accumulate_matrix_seconds(self, now_ms: int, dt_seconds: float) -> None:
        if dt_seconds <= 0:
            return
        for source_key, level in self._active_levels_by_source.items():
            bucket = str(level.get("bucket_key") or "")
            if source_key not in SOURCE_KEYS or bucket not in SEVERITY_KEYS:
                continue
            self._matrix_seconds_events.append(
                _MatrixSecondsEvent(
                    ts_ms=now_ms,
                    source_key=source_key,
                    severity_key=bucket,
                    dt_seconds=float(dt_seconds),
                )
            )

    def _prune_matrix_windows(self, now_ms: int) -> None:
        cutoff_ms = now_ms - _MATRIX_WINDOW_MS
        while self._matrix_count_events and self._matrix_count_events[0].ts_ms < cutoff_ms:
            self._matrix_count_events.popleft()
        while self._matrix_seconds_events and self._matrix_seconds_events[0].ts_ms < cutoff_ms:
            self._matrix_seconds_events.popleft()

    def _rebuild_matrix(self, now_ms: int) -> None:
        self._prune_matrix_windows(now_ms)
        matrix = _new_matrix()

        for event in self._matrix_count_events:
            cell = matrix[event.source_key][event.severity_key]
            cell["count"] = int(cell.get("count", 0)) + 1
            contributors = cell["contributors"]
            contributors[event.contributor_label] = (
                int(contributors.get(event.contributor_label, 0)) + 1
            )

        for event in self._matrix_seconds_events:
            cell = matrix[event.source_key][event.severity_key]
            cell["seconds"] = float(cell.get("seconds", 0.0)) + float(event.dt_seconds)

        self._matrix = matrix

    def _update_matrix_many(
        self,
        now_ms: int,
        source_keys: tuple[str, ...],
        severity_key: str,
        contributor_label: str,
    ) -> None:
        for source_key in source_keys:
            self._record_matrix_count(now_ms, source_key, severity_key, contributor_label)

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

    def _apply_severity_to_tracker(
        self,
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
            peak_hz=tracker.last_peak_hz if tracker.last_peak_hz > 0 else None,
            persistence_freq_bin_hz=self._multi_freq_bin_hz,
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
        sensor_location: str,
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
                    "sensor_location": sensor_location,
                    "class_key": class_key,
                    "peak_hz": peak_hz,
                }

    @staticmethod
    def _location_key(sensor_location: str) -> str | None:
        key = str(sensor_location or "").strip()
        return key or None

    def _build_active_levels_by_location(
        self,
        *,
        candidates_by_location: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        by_location: dict[str, dict[str, Any]] = {}
        for location_key, candidates in candidates_by_location.items():
            if not candidates:
                continue
            dominant = max(candidates, key=lambda row: float(row.get("strength_db", SILENCE_DB)))
            dominant_bin = (
                str(dominant.get("class_key") or ""),
                str(dominant.get("bucket_key") or ""),
                int(round(float(dominant.get("peak_hz") or 0.0) / self._multi_freq_bin_hz)),
            )
            agreeing_ids = {
                str(row.get("sensor_id") or "")
                for row in candidates
                if (
                    str(row.get("class_key") or ""),
                    str(row.get("bucket_key") or ""),
                    int(round(float(row.get("peak_hz") or 0.0) / self._multi_freq_bin_hz)),
                )
                == dominant_bin
                and str(row.get("sensor_id") or "")
            }
            agreement_count = len(agreeing_ids)
            confidence = 1.0 + max(0, agreement_count - 1)
            by_location[location_key] = {
                "bucket_key": str(dominant.get("bucket_key") or ""),
                "strength_db": float(dominant.get("strength_db", SILENCE_DB)),
                "sensor_label": str(dominant.get("sensor_label") or ""),
                "sensor_location": location_key,
                "class_key": str(dominant.get("class_key") or ""),
                "peak_hz": float(dominant.get("peak_hz") or 0.0),
                "confidence": float(confidence),
                "agreement_count": agreement_count,
                "sensor_count": len(
                    {
                        str(row.get("sensor_id") or "")
                        for row in candidates
                        if str(row.get("sensor_id") or "")
                    }
                ),
            }
        return by_location

    def _update_driving_phase(self, speed_mps: float | None, now_s: float) -> None:
        """Classify the current driving phase from a rolling speed window."""
        speed_kmh: float | None = speed_mps * MPS_TO_KMH if speed_mps is not None else None
        self._phase_speed_history.append((now_s, speed_kmh))
        if len(self._phase_speed_history) > _PHASE_HISTORY_MAX:
            self._phase_speed_history = self._phase_speed_history[-_PHASE_HISTORY_MAX:]
        deriv: float | None = None
        valid = [(t, s) for t, s in self._phase_speed_history if s is not None]
        if len(valid) >= 2:
            t0, s0 = valid[0]
            t1, s1 = valid[-1]
            dt = t1 - t0
            if dt >= 0.1:
                deriv = (s1 - s0) / dt
        self._current_phase = _classify_sample_phase(speed_kmh, deriv).value

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
            "diagnostics_sequence": self._diagnostics_sequence,
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
                "by_location": {
                    key: dict(value) for key, value in self._active_levels_by_location.items()
                },
            },
            "findings": list(self._latest_findings),
            "top_finding": top_finding,
            "driving_phase": self._current_phase,
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
        language: str = "en",
    ) -> dict[str, Any]:
        if finding_metadata is not None and finding_samples is not None:
            try:
                self._latest_findings = build_findings_for_samples(
                    metadata=finding_metadata,
                    samples=finding_samples,
                    lang=language,
                )
            except ValueError as exc:
                LOGGER.warning("Live diagnostics findings unavailable: %s", exc)
                self._latest_findings = []

        now_ms = int(monotonic() * 1000.0)
        self._update_driving_phase(speed_mps, now_ms / 1000.0)

        # Accumulate matrix dwell-seconds on *every* tick (including light
        # ticks where spectra is None) so that dwell time stays accurate
        # regardless of the heavy/light WS cadence.
        dt_seconds = 0.0
        if self._last_update_ts_ms is not None:
            dt_seconds = max(0.0, min(1.0, (now_ms - self._last_update_ts_ms) / 1000.0))
        self._last_update_ts_ms = now_ms
        self._accumulate_matrix_seconds(now_ms, dt_seconds)
        self._rebuild_matrix(now_ms)

        if spectra is None:
            self._last_error = None
            return self.snapshot()

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
        location_candidates: dict[str, list[dict[str, Any]]] = {}

        latest_by_tracker: dict[str, _RecentEvent] = {}
        for event in sensor_events:
            tracker_key = f"{event.sensor_id}:{event.class_key}"
            previous = latest_by_tracker.get(tracker_key)
            if previous is None or event.vibration_strength_db > previous.vibration_strength_db:
                latest_by_tracker[tracker_key] = event

        for tracker_key, event in latest_by_tracker.items():
            tracker = self._sensor_trackers.get(tracker_key) or _TrackerLevelState()
            tracker.last_peak_hz = float(event.peak_hz)
            previous_bucket = self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=event.vibration_strength_db,
                sensor_count=1,
            )
            tracker.last_band_rms_g = float(event.peak_amp)
            tracker.last_update_ms = now_ms
            tracker.last_class_key = event.class_key
            tracker.last_sensor_label = event.sensor_label
            tracker.last_sensor_location = event.sensor_location
            self._sensor_trackers[tracker_key] = tracker

            if tracker.current_bucket_key:
                source_keys = source_keys_from_class_key(event.class_key)
                self._upsert_active_level(
                    active_by_source=active_by_source,
                    source_keys=source_keys,
                    bucket_key=tracker.current_bucket_key,
                    strength_db=tracker.last_strength_db,
                    sensor_label=event.sensor_label,
                    sensor_location=event.sensor_location,
                    class_key=event.class_key,
                    peak_hz=event.peak_hz,
                )
                self._update_sensor_active_level(
                    active_by_sensor,
                    event.sensor_id,
                    bucket_key=tracker.current_bucket_key,
                    strength_db=tracker.last_strength_db,
                    class_key=event.class_key,
                    peak_hz=event.peak_hz,
                )

            should_emit = self._should_emit_event(
                tracker=tracker,
                previous_bucket=previous_bucket,
                current_bucket=tracker.current_bucket_key,
                now_ms=now_ms,
            )
            matrix_bucket = self._matrix_transition_bucket(
                previous_bucket, tracker.current_bucket_key
            )
            if should_emit and tracker.current_bucket_key:
                matrix_bucket = tracker.current_bucket_key
            if matrix_bucket:
                source_keys = source_keys_from_class_key(event.class_key)
                self._update_matrix_many(
                    now_ms,
                    source_keys,
                    matrix_bucket,
                    event.sensor_label,
                )

            if should_emit:
                tracker.last_emitted_ms = now_ms
                event_id = self._next_event_id
                self._next_event_id += 1
                emitted_events.append(
                    {
                        "event_id": event_id,
                        "kind": "single",
                        "class_key": event.class_key,
                        "sensor_count": 1,
                        "sensor_id": event.sensor_id,
                        "sensor_label": event.sensor_label,
                        "sensor_labels": [event.sensor_label],
                        "peak_hz": event.peak_hz,
                        "peak_amp": event.peak_amp,
                        "peak_amp_g": event.peak_amp,
                        "severity_key": tracker.current_bucket_key,
                        "vibration_strength_db": tracker.last_strength_db,
                    }
                )

        self._decay_unseen_sensor_trackers(set(latest_by_tracker))
        self._collect_active_levels_from_trackers(
            active_by_source, active_by_sensor, location_candidates
        )

        seen_combined_keys = self._process_combined_groups(
            now_ms=now_ms,
            active_by_source=active_by_source,
            emitted_events=emitted_events,
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
        self._active_levels_by_location = self._build_active_levels_by_location(
            candidates_by_location=location_candidates
        )
        self._rebuild_matrix(now_ms)
        self._latest_events = emitted_events
        self._diagnostics_sequence += 1
        return self.snapshot()

    def _decay_unseen_sensor_trackers(self, seen_keys: set[str]) -> None:
        """Apply silence decay to sensor trackers not seen in the current tick."""
        for tracker_key, tracker in list(self._sensor_trackers.items()):
            if tracker_key in seen_keys:
                continue
            self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=SILENCE_DB,
                sensor_count=1,
                fallback_db=SILENCE_DB,
            )

    def _collect_active_levels_from_trackers(
        self,
        active_by_source: dict[str, dict[str, Any]],
        active_by_sensor: dict[str, dict[str, Any]],
        location_candidates: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Rebuild source/sensor/location active levels from all tracker state."""
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
                sensor_location=tracker.last_sensor_location,
                class_key=class_key or tracker.last_class_key,
                peak_hz=tracker.last_peak_hz,
            )
            self._update_sensor_active_level(
                active_by_sensor,
                sensor_id,
                bucket_key=tracker.current_bucket_key,
                strength_db=tracker.last_strength_db,
                class_key=class_key or tracker.last_class_key,
                peak_hz=tracker.last_peak_hz,
            )
            location_key = self._location_key(tracker.last_sensor_location)
            if location_key:
                location_candidates.setdefault(location_key, []).append(
                    {
                        "sensor_id": sensor_id,
                        "sensor_label": tracker.last_sensor_label,
                        "bucket_key": tracker.current_bucket_key,
                        "strength_db": tracker.last_strength_db,
                        "class_key": class_key or tracker.last_class_key,
                        "peak_hz": tracker.last_peak_hz,
                    }
                )

    @staticmethod
    def _update_sensor_active_level(
        active_by_sensor: dict[str, dict[str, Any]],
        sensor_id: str,
        *,
        bucket_key: str,
        strength_db: float,
        class_key: str,
        peak_hz: float,
    ) -> None:
        """Keep only the strongest active level per sensor."""
        existing = active_by_sensor.get(sensor_id)
        if existing is None or strength_db > float(existing.get("strength_db", -1e9)):
            active_by_sensor[sensor_id] = {
                "bucket_key": bucket_key,
                "strength_db": strength_db,
                "class_key": class_key,
                "peak_hz": peak_hz,
            }

    def _process_combined_groups(
        self,
        *,
        now_ms: int,
        active_by_source: dict[str, dict[str, Any]],
        emitted_events: list[dict[str, Any]],
    ) -> set[str]:
        """Build and process multi-sensor combined groups.

        Returns the set of combined tracker keys that were active this tick.
        """
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
                avg_strength = _combine_amplitude_strength_db(
                    [item.last_strength_db for item in group]
                )
                freq_bin = round(avg_hz / self._multi_freq_bin_hz)
                combined_key = f"combined:{class_key}:{freq_bin}"
                seen_combined_keys.add(combined_key)
                tracker = self._combined_trackers.get(combined_key) or _TrackerLevelState(
                    last_class_key=class_key
                )
                tracker.last_peak_hz = avg_hz
                previous_bucket = self._apply_severity_to_tracker(
                    tracker,
                    vibration_strength_db=avg_strength,
                    sensor_count=len(group),
                )
                tracker.last_band_rms_g = avg_amp
                tracker.last_update_ms = now_ms
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
                        sensor_location=tracker.last_sensor_location,
                        class_key=class_key,
                        peak_hz=avg_hz,
                    )

                should_emit = self._should_emit_event(
                    tracker=tracker,
                    previous_bucket=previous_bucket,
                    current_bucket=tracker.current_bucket_key,
                    now_ms=now_ms,
                )
                matrix_bucket = self._matrix_transition_bucket(
                    previous_bucket, tracker.current_bucket_key
                )
                if should_emit and tracker.current_bucket_key:
                    matrix_bucket = tracker.current_bucket_key
                if matrix_bucket:
                    source_keys = source_keys_from_class_key(class_key)
                    self._update_matrix_many(
                        now_ms, source_keys, matrix_bucket, tracker.last_sensor_label
                    )

                if should_emit:
                    tracker.last_emitted_ms = now_ms
                    event_id = self._next_event_id
                    self._next_event_id += 1
                    emitted_events.append(
                        {
                            "event_id": event_id,
                            "kind": "multi",
                            "class_key": class_key,
                            "sensor_count": len(group),
                            "sensor_labels": [item.last_sensor_label for item in group],
                            "peak_hz": avg_hz,
                            "peak_amp": avg_amp,
                            "peak_amp_g": avg_amp,
                            "severity_key": tracker.current_bucket_key,
                            "vibration_strength_db": tracker.last_strength_db,
                        }
                    )

        return seen_combined_keys

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
        client_location_map = {
            str(client.get("id")): str(client.get("location") or "")
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
