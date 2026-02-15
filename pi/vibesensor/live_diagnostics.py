from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from .diagnostics_shared import (
    build_diagnostic_settings,
    classify_peak_hz,
    severity_from_peak,
    source_keys_from_class_key,
)
from .report_analysis import build_findings_for_samples

SOURCE_KEYS = ("engine", "driveshaft", "wheel", "other")
SEVERITY_KEYS = ("l5", "l4", "l3", "l2", "l1")


def _new_matrix() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        source: {severity: {"count": 0, "contributors": {}} for severity in SEVERITY_KEYS}
        for source in SOURCE_KEYS
    }


def _copy_matrix(
    matrix: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    return {
        source: {
            severity: {
                "count": int(cell.get("count", 0)),
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
    floor_amp: float
    class_key: str


class LiveDiagnosticsEngine:
    def __init__(self) -> None:
        self._matrix = _new_matrix()
        self._recent_events: list[_RecentEvent] = []
        self._last_detection_by_client: dict[str, dict[str, float | int]] = {}
        self._last_detection_global: dict[str, dict[str, float | int]] = {}
        self._multi_sync_window_ms = 500
        self._multi_freq_bin_hz = 1.5
        self._latest_events: list[dict[str, Any]] = []
        self._latest_findings: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._matrix = _new_matrix()
        self._recent_events = []
        self._last_detection_by_client = {}
        self._last_detection_global = {}
        self._latest_events = []
        self._latest_findings = []

    def _update_matrix(self, source_key: str, severity_key: str, contributor_label: str) -> None:
        if source_key not in self._matrix:
            return
        cell = self._matrix[source_key].get(severity_key)
        if cell is None:
            return
        cell["count"] = int(cell["count"]) + 1
        contributors = cell["contributors"]
        contributors[contributor_label] = int(contributors.get(contributor_label, 0)) + 1

    def _update_matrix_many(
        self, source_keys: tuple[str, ...], severity_key: str, contributor_label: str
    ) -> None:
        for source_key in source_keys:
            self._update_matrix(source_key, severity_key, contributor_label)

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
            "findings": list(self._latest_findings),
            "top_finding": top_finding,
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
            except Exception:
                self._latest_findings = []

        if spectra is None:
            self._latest_events = []
            return self.snapshot()

        now_ms = int(monotonic() * 1000.0)
        sensor_events = self._detect_sensor_events(
            speed_mps=speed_mps,
            clients=clients,
            spectra=spectra,
            settings=settings or {},
        )
        self._recent_events.extend(sensor_events)
        cutoff = now_ms - self._multi_sync_window_ms
        self._recent_events = [event for event in self._recent_events if event.ts_ms >= cutoff]

        emitted_events: list[dict[str, Any]] = []
        used_sensor_ids: set[str] = set()
        grouped: dict[str, dict[str, _RecentEvent]] = {}
        for event in self._recent_events:
            freq_bin = round(event.peak_hz / self._multi_freq_bin_hz)
            key = f"{event.class_key}:{freq_bin}"
            sensor_map = grouped.setdefault(key, {})
            previous = sensor_map.get(event.sensor_id)
            if previous is None or event.ts_ms > previous.ts_ms:
                sensor_map[event.sensor_id] = event

        for group_key, sensor_map in grouped.items():
            group = list(sensor_map.values())
            if len(group) < 2:
                continue
            avg_hz = sum(event.peak_hz for event in group) / len(group)
            avg_amp = sum(event.peak_amp for event in group) / len(group)
            avg_floor = sum(event.floor_amp for event in group) / len(group)
            previous = self._last_detection_global.get(group_key)
            if previous is not None:
                prev_ts = int(previous["ts_ms"])
                prev_hz = float(previous["peak_hz"])
                if now_ms - prev_ts < 3000 and abs(prev_hz - avg_hz) < 1.2:
                    continue
            self._last_detection_global[group_key] = {"ts_ms": now_ms, "peak_hz": avg_hz}

            severity = severity_from_peak(
                peak_amp=avg_amp,
                floor_amp=avg_floor,
                sensor_count=len(group),
            )
            if severity is None:
                continue
            class_key = group[0].class_key
            source_keys = source_keys_from_class_key(class_key)
            labels = [event.sensor_label for event in group]
            contributor = f"combined({', '.join(labels)})"
            self._update_matrix_many(source_keys, str(severity["key"]), contributor)
            for event in group:
                used_sensor_ids.add(event.sensor_id)
            emitted_events.append(
                {
                    "kind": "multi",
                    "class_key": class_key,
                    "sensor_count": len(group),
                    "sensor_labels": labels,
                    "peak_hz": avg_hz,
                    "peak_amp": avg_amp,
                    "severity_key": str(severity["key"]),
                    "severity_db": float(severity["db"]),
                }
            )

        for event in sensor_events:
            if event.sensor_id in used_sensor_ids:
                continue
            dedupe_key = f"{event.sensor_id}:{event.class_key}"
            previous = self._last_detection_by_client.get(dedupe_key)
            if previous is not None:
                prev_ts = int(previous["ts_ms"])
                prev_hz = float(previous["peak_hz"])
                if now_ms - prev_ts < 3500 and abs(prev_hz - event.peak_hz) < 1.0:
                    continue
            self._last_detection_by_client[dedupe_key] = {"ts_ms": now_ms, "peak_hz": event.peak_hz}
            severity = severity_from_peak(
                peak_amp=event.peak_amp,
                floor_amp=event.floor_amp,
                sensor_count=1,
            )
            if severity is None:
                continue
            source_keys = source_keys_from_class_key(event.class_key)
            self._update_matrix_many(source_keys, str(severity["key"]), event.sensor_label)
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
                    "severity_key": str(severity["key"]),
                    "severity_db": float(severity["db"]),
                }
            )

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
        fallback_freq = [
            float(value)
            for value in (spectra.get("freq") if isinstance(spectra.get("freq"), list) else [])
            if isinstance(value, (int, float))
        ]
        client_map = {
            str(client.get("id")): str(client.get("name") or client.get("id") or "")
            for client in clients
            if isinstance(client, dict)
        }
        clients_payload = spectra.get("clients")
        if not isinstance(clients_payload, dict):
            return []

        settings_bundle = build_diagnostic_settings(settings)
        entries: list[tuple[str, str, list[float], list[float]]] = []
        target_freq: list[float] = []
        for client_id, payload in clients_payload.items():
            if not isinstance(payload, dict):
                continue
            x_raw = payload.get("x")
            y_raw = payload.get("y")
            z_raw = payload.get("z")
            if (
                not isinstance(x_raw, list)
                or not isinstance(y_raw, list)
                or not isinstance(z_raw, list)
            ):
                continue
            client_freq_raw = payload.get("freq")
            client_freq = (
                [float(v) for v in client_freq_raw if isinstance(v, (int, float))]
                if isinstance(client_freq_raw, list) and client_freq_raw
                else fallback_freq
            )
            n = min(len(client_freq), len(x_raw), len(y_raw), len(z_raw))
            if n <= 0:
                continue
            blend: list[float] = []
            freq_slice = client_freq[:n]
            for idx in range(n):
                x = float(x_raw[idx])
                y = float(y_raw[idx])
                z = float(z_raw[idx])
                blend.append(((x * x) + (y * y) + (z * z)) / 3.0)
            blend = [value**0.5 for value in blend]
            if not target_freq:
                target_freq = freq_slice
            elif len(freq_slice) != len(target_freq) or any(
                abs(freq_slice[idx] - target_freq[idx]) > 1e-6 for idx in range(len(target_freq))
            ):
                blend = _interpolate_to_target(freq_slice, blend, target_freq)
            if not blend:
                continue
            label = client_map.get(str(client_id), str(client_id))
            entries.append((str(client_id), label, target_freq, blend))

        now_ms = int(monotonic() * 1000.0)
        events: list[_RecentEvent] = []
        for client_id, label, freq, values in entries:
            if len(values) < 10:
                continue
            tail = values[5:] if len(values) > 5 else values
            floor_sorted = sorted(tail)
            floor_amp = floor_sorted[len(floor_sorted) // 2] if floor_sorted else 0.0

            local_maxima: list[int] = []
            for idx in range(2, len(values) - 2):
                if values[idx] > values[idx - 1] and values[idx] >= values[idx + 1]:
                    local_maxima.append(idx)
            local_maxima.sort(key=lambda idx: values[idx], reverse=True)

            chosen: list[int] = []
            for idx in local_maxima:
                if len(chosen) >= 4:
                    break
                if values[idx] <= max(40.0, floor_amp * 2.6):
                    continue
                if any(abs(freq[prev] - freq[idx]) < 1.2 for prev in chosen):
                    continue
                chosen.append(idx)

            for idx in chosen:
                peak_hz = float(freq[idx])
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
                        peak_amp=float(values[idx]),
                        floor_amp=float(floor_amp),
                        class_key=str(classification["key"]),
                    )
                )
        return events
