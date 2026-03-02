"""Severity matrix — windowed count/dwell-time aggregation by source × severity."""

from __future__ import annotations

from collections import deque
from typing import Any

from ._types import (
    _MATRIX_WINDOW_MS,
    SEVERITY_KEYS,
    SOURCE_KEYS,
    _MatrixCountEvent,
    _MatrixSecondsEvent,
)


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


class SeverityMatrix:
    """Windowed matrix tracking event counts and dwell-seconds per source × severity."""

    __slots__ = ("_matrix", "_count_events", "_seconds_events")

    def __init__(self) -> None:
        self._matrix = _new_matrix()
        self._count_events: deque[_MatrixCountEvent] = deque(maxlen=10_000)
        self._seconds_events: deque[_MatrixSecondsEvent] = deque(maxlen=10_000)

    def reset(self) -> None:
        self._matrix = _new_matrix()
        self._count_events.clear()
        self._seconds_events.clear()

    @property
    def data(self) -> dict[str, dict[str, dict[str, Any]]]:
        return self._matrix

    def copy(self) -> dict[str, dict[str, dict[str, Any]]]:
        return _copy_matrix(self._matrix)

    def record_count(
        self,
        now_ms: int,
        source_key: str,
        severity_key: str,
        contributor_label: str,
    ) -> None:
        if source_key not in SOURCE_KEYS or severity_key not in SEVERITY_KEYS:
            return
        self._count_events.append(
            _MatrixCountEvent(
                ts_ms=now_ms,
                source_key=source_key,
                severity_key=severity_key,
                contributor_label=contributor_label,
            )
        )

    def record_many(
        self,
        now_ms: int,
        source_keys: tuple[str, ...],
        severity_key: str,
        contributor_label: str,
    ) -> None:
        for source_key in source_keys:
            self.record_count(now_ms, source_key, severity_key, contributor_label)

    def accumulate_seconds(
        self,
        now_ms: int,
        dt_seconds: float,
        active_levels_by_source: dict[str, dict[str, Any]],
    ) -> None:
        if dt_seconds <= 0:
            return
        for source_key, level in active_levels_by_source.items():
            bucket = str(level.get("bucket_key") or "")
            if source_key not in SOURCE_KEYS or bucket not in SEVERITY_KEYS:
                continue
            self._seconds_events.append(
                _MatrixSecondsEvent(
                    ts_ms=now_ms,
                    source_key=source_key,
                    severity_key=bucket,
                    dt_seconds=float(dt_seconds),
                )
            )

    def _prune(self, now_ms: int) -> None:
        cutoff_ms = now_ms - _MATRIX_WINDOW_MS
        while self._count_events and self._count_events[0].ts_ms < cutoff_ms:
            self._count_events.popleft()
        while self._seconds_events and self._seconds_events[0].ts_ms < cutoff_ms:
            self._seconds_events.popleft()

    def rebuild(self, now_ms: int) -> None:
        self._prune(now_ms)
        matrix = _new_matrix()
        for event in self._count_events:
            cell = matrix[event.source_key][event.severity_key]
            cell["count"] = int(cell.get("count", 0)) + 1
            contributors = cell["contributors"]
            contributors[event.contributor_label] = (
                int(contributors.get(event.contributor_label, 0)) + 1
            )
        for event in self._seconds_events:
            cell = matrix[event.source_key][event.severity_key]
            cell["seconds"] = float(cell.get("seconds", 0.0)) + float(event.dt_seconds)
        self._matrix = matrix
