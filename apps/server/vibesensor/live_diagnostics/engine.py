"""LiveDiagnosticsEngine — thin orchestrator composing focused components."""

from __future__ import annotations

import logging
from collections import deque
from time import monotonic
from typing import Any

from vibesensor_core.strength_bands import BANDS

from ..analysis import build_findings_for_samples
from ..constants import SILENCE_DB
from ..diagnostics_shared import source_keys_from_class_key
from ._types import (
    _HEARTBEAT_EMIT_INTERVAL_MS,
    _MULTI_FREQ_BIN_HZ,
    _MULTI_SYNC_WINDOW_MS,
    _combine_amplitude_strength_db,
    _RecentEvent,
    _TrackerLevelState,
)
from .active_levels import (
    build_active_levels_by_location,
    collect_active_levels_from_trackers,
    update_sensor_active_level,
    upsert_active_level,
)
from .event_detector import detect_sensor_events
from .phase_classifier import PhaseClassifier
from .severity_matrix import SeverityMatrix
from .tracker import (
    apply_severity_to_tracker,
    matrix_transition_bucket,
    should_emit_event,
)

LOGGER = logging.getLogger(__name__)


class LiveDiagnosticsEngine:
    def __init__(self) -> None:
        self._matrix = SeverityMatrix()
        self._sensor_trackers: dict[str, _TrackerLevelState] = {}
        self._combined_trackers: dict[str, _TrackerLevelState] = {}
        self._multi_sync_window_ms = _MULTI_SYNC_WINDOW_MS
        self._multi_freq_bin_hz = _MULTI_FREQ_BIN_HZ
        self._heartbeat_emit_ms = _HEARTBEAT_EMIT_INTERVAL_MS
        self._latest_events: list[dict[str, Any]] = []
        self._latest_findings: list[dict[str, Any]] = []
        self._active_levels_by_source: dict[str, dict[str, Any]] = {}
        self._active_levels_by_sensor: dict[str, dict[str, Any]] = {}
        self._active_levels_by_location: dict[str, dict[str, Any]] = {}
        self._last_update_ts_ms: int | None = None
        self._last_error: str | None = None
        self._phase = PhaseClassifier()
        self._current_phase: str = self._phase.current_phase
        self._diagnostics_sequence: int = 0
        self._next_event_id: int = 0

    def reset(self) -> None:
        self._matrix.reset()
        self._sensor_trackers = {}
        self._combined_trackers = {}
        self._latest_events = []
        self._latest_findings = []
        self._active_levels_by_source = {}
        self._active_levels_by_sensor = {}
        self._active_levels_by_location = {}
        self._last_update_ts_ms = None
        self._last_error = None
        self._phase.reset()
        self._current_phase = self._phase.current_phase
        self._diagnostics_sequence = 0
        self._next_event_id = 0

    # ------------------------------------------------------------------
    # Delegation wrappers — kept as methods so tests can monkeypatch them
    # ------------------------------------------------------------------

    def _apply_severity_to_tracker(
        self,
        tracker: _TrackerLevelState,
        *,
        vibration_strength_db: float,
        sensor_count: int,
        fallback_db: float | None = None,
    ) -> str | None:
        return apply_severity_to_tracker(
            tracker,
            vibration_strength_db,
            sensor_count,
            self._multi_freq_bin_hz,
            fallback_db,
        )

    def _detect_sensor_events(
        self,
        *,
        speed_mps: float | None,
        clients: list[dict[str, Any]],
        spectra: dict[str, Any],
        settings: dict[str, float],
    ) -> list[_RecentEvent]:
        return detect_sensor_events(
            speed_mps=speed_mps,
            clients=clients,
            spectra=spectra,
            settings=settings,
        )

    def _should_emit_event(
        self,
        *,
        tracker: _TrackerLevelState,
        previous_bucket: str | None,
        current_bucket: str | None,
        now_ms: int,
    ) -> bool:
        return should_emit_event(
            tracker=tracker,
            previous_bucket=previous_bucket,
            current_bucket=current_bucket,
            now_ms=now_ms,
            heartbeat_ms=self._heartbeat_emit_ms,
        )

    def _matrix_transition_bucket(
        self, previous_bucket: str | None, current_bucket: str | None
    ) -> str | None:
        return matrix_transition_bucket(previous_bucket, current_bucket)

    @staticmethod
    def _location_key(sensor_location: str) -> str | None:
        from .active_levels import location_key

        return location_key(sensor_location)

    @property
    def _phase_speed_history(self) -> deque[tuple[float, float | None]]:
        return self._phase._speed_history

    @_phase_speed_history.setter
    def _phase_speed_history(self, value: deque[tuple[float, float | None]]) -> None:
        self._phase._speed_history = value

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

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
            "matrix": self._matrix.copy(),
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

    # ------------------------------------------------------------------
    # Main update loop
    # ------------------------------------------------------------------

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
            except Exception as exc:
                LOGGER.warning("Live diagnostics findings unavailable: %s", exc)
                self._latest_findings = []

        now_ms = int(monotonic() * 1000.0)
        self._phase.update(speed_mps, now_ms / 1000.0)
        self._current_phase = self._phase.current_phase

        dt_seconds = 0.0
        if self._last_update_ts_ms is not None:
            dt_seconds = max(0.0, min(1.0, (now_ms - self._last_update_ts_ms) / 1000.0))
        self._last_update_ts_ms = now_ms
        self._matrix.accumulate_seconds(now_ms, dt_seconds, self._active_levels_by_source)
        self._matrix.rebuild(now_ms)

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
        except Exception as exc:
            LOGGER.warning(
                "Live diagnostics update skipped due to invalid spectra payload: %s",
                exc,
            )
            self._last_error = str(exc)
            sensor_events = []

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
                upsert_active_level(
                    active_by_source=active_by_source,
                    source_keys=source_keys,
                    bucket_key=tracker.current_bucket_key,
                    strength_db=tracker.last_strength_db,
                    sensor_label=event.sensor_label,
                    sensor_location=event.sensor_location,
                    class_key=event.class_key,
                    peak_hz=event.peak_hz,
                )
                update_sensor_active_level(
                    active_by_sensor,
                    event.sensor_id,
                    bucket_key=tracker.current_bucket_key,
                    strength_db=tracker.last_strength_db,
                    class_key=event.class_key,
                    peak_hz=event.peak_hz,
                )

            _should_emit = self._should_emit_event(
                tracker=tracker,
                previous_bucket=previous_bucket,
                current_bucket=tracker.current_bucket_key,
                now_ms=now_ms,
            )
            _matrix_bucket = self._matrix_transition_bucket(
                previous_bucket, tracker.current_bucket_key
            )
            if _should_emit and tracker.current_bucket_key:
                _matrix_bucket = tracker.current_bucket_key
            if _matrix_bucket:
                source_keys = source_keys_from_class_key(event.class_key)
                self._matrix.record_many(
                    now_ms,
                    source_keys,
                    _matrix_bucket,
                    event.sensor_label,
                )

            if _should_emit:
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
        collect_active_levels_from_trackers(
            self._sensor_trackers, active_by_source, active_by_sensor, location_candidates
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
            if tracker.current_bucket_key is None and (now_ms - tracker.last_update_ms) > 30_000:
                del self._combined_trackers[combined_key]

        self._active_levels_by_source = active_by_source
        self._active_levels_by_sensor = active_by_sensor
        self._active_levels_by_location = build_active_levels_by_location(
            candidates_by_location=location_candidates,
            freq_bin_hz=self._multi_freq_bin_hz,
        )
        self._matrix.rebuild(now_ms)
        self._latest_events = emitted_events
        self._diagnostics_sequence += 1
        return self.snapshot()

    # ------------------------------------------------------------------
    # Tracker lifecycle
    # ------------------------------------------------------------------

    def _decay_unseen_sensor_trackers(self, seen_keys: set[str]) -> None:
        """Apply silence decay to sensor trackers not seen in the current tick."""
        _PRUNE_SILENCE_TICKS = 60
        for tracker_key, tracker in list(self._sensor_trackers.items()):
            if tracker_key in seen_keys:
                tracker._silence_ticks = 0
                continue
            self._apply_severity_to_tracker(
                tracker,
                vibration_strength_db=SILENCE_DB,
                sensor_count=1,
                fallback_db=SILENCE_DB,
            )
            tracker._silence_ticks += 1
            if tracker._silence_ticks >= _PRUNE_SILENCE_TICKS:
                del self._sensor_trackers[tracker_key]

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
                if self._multi_freq_bin_hz > 0:
                    freq_bin = round(avg_hz / self._multi_freq_bin_hz)
                else:
                    freq_bin = 0
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
                    upsert_active_level(
                        active_by_source=active_by_source,
                        source_keys=source_keys,
                        bucket_key=tracker.current_bucket_key,
                        strength_db=tracker.last_strength_db,
                        sensor_label=tracker.last_sensor_label,
                        sensor_location=tracker.last_sensor_location,
                        class_key=class_key,
                        peak_hz=avg_hz,
                    )

                _should_emit = self._should_emit_event(
                    tracker=tracker,
                    previous_bucket=previous_bucket,
                    current_bucket=tracker.current_bucket_key,
                    now_ms=now_ms,
                )
                _matrix_bucket = self._matrix_transition_bucket(
                    previous_bucket, tracker.current_bucket_key
                )
                if _should_emit and tracker.current_bucket_key:
                    _matrix_bucket = tracker.current_bucket_key
                if _matrix_bucket:
                    source_keys = source_keys_from_class_key(class_key)
                    self._matrix.record_many(
                        now_ms, source_keys, _matrix_bucket, tracker.last_sensor_label
                    )

                if _should_emit:
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
