from __future__ import annotations

import ast
import json
import math
import re
import time
from dataclasses import dataclass
from math import floor

from tests_e2e._docker_edge_helpers import (
    _cleanup_clients,
    _cleanup_run,
    _prepare_simulator_locations,
)
from tests_e2e.e2e_helpers import (
    api_bytes,
    api_json,
    history_run_ids,
    non_ref_findings,
    normalize_location,
    parse_export_zip,
    pdf_text,
    run_cleanup_steps,
    run_simulator,
    wait_for,
    wait_run_status,
)
from vibesensor.vibration_strength import percentile


@dataclass(frozen=True)
class WheelFaultArtifacts:
    run_id: str
    insights: dict
    run_analysis: dict
    export_samples: list[dict]
    pdf_bytes: bytes


def run_localized_wheel_fault_capture(
    e2e_env: dict[str, str],
    *,
    fault_wheel: str,
) -> str:
    base_url = e2e_env["base_url"]
    _cleanup_clients(base_url)
    wait_for(
        lambda: not api_json(base_url, "/api/clients").get("clients"),
        timeout_s=5.0,
        interval_s=0.5,
        message="simulator clients did not quiesce before wheel-fault E2E run",
    )
    time.sleep(2.5)
    _prepare_simulator_locations(e2e_env)

    api_json(
        base_url,
        "/api/settings/speed-source",
        method="PUT",
        body={"speed_source": "manual", "manual_speed_kph": 100.0},
    )
    start = api_json(base_url, "/api/recording/start", method="POST")
    assert start["enabled"] is True
    run_id = str(start["run_id"])

    run_simulator(
        base_url=base_url,
        sim_host=e2e_env["sim_host"],
        sim_data_port=e2e_env["sim_data_port"],
        sim_control_port=e2e_env["sim_control_port"],
        duration_s=float(e2e_env["sim_duration"]),
        count=4,
        fault_wheel=fault_wheel,
    )

    api_json(base_url, "/api/recording/stop", method="POST")
    wait_for(
        lambda: run_id if run_id in history_run_ids(base_url) else None,
        timeout_s=10.0,
        interval_s=0.5,
        message=f"Run {run_id} did not become visible in history",
    )
    run = api_json(base_url, f"/api/history/{run_id}")
    assert run.get("status") in {"analyzing", "complete"}
    wait_run_status(base_url, run_id, timeout_s=90.0)
    return run_id


def fetch_wheel_fault_artifacts(base_url: str, run_id: str) -> WheelFaultArtifacts:
    insights = api_json(base_url, f"/api/history/{run_id}/insights")
    pdf_resp = api_bytes(base_url, f"/api/history/{run_id}/report.pdf?lang=en")
    assert str(pdf_resp.headers.get("content-type", "")).startswith("application/pdf")
    assert pdf_resp.body[:5] == b"%PDF-"

    run_payload = api_json(base_url, f"/api/history/{run_id}")
    export_resp = api_bytes(base_url, f"/api/history/{run_id}/export")
    assert str(export_resp.headers.get("content-type", "")).startswith("application/zip")
    _, raw_export_samples, _ = parse_export_zip(export_resp.body)
    export_samples = [
        {k: _parse_csv_value(v) for k, v in row.items()} for row in raw_export_samples
    ]
    return WheelFaultArtifacts(
        run_id=run_id,
        insights=insights,
        run_analysis=run_payload.get("analysis") or {},
        export_samples=export_samples,
        pdf_bytes=pdf_resp.body,
    )


def assert_localized_wheel_fault_summary(
    artifacts: WheelFaultArtifacts,
    *,
    expected_location: str,
) -> dict:
    findings = non_ref_findings(artifacts.insights)
    assert findings, "Expected non-reference findings"

    primary = findings[0]
    assert primary.get("suspected_source") == "wheel/tire"
    primary_location = normalize_location(str(primary.get("strongest_location") or ""))
    assert expected_location in primary_location

    top_causes = [
        item for item in artifacts.insights.get("top_causes", []) if isinstance(item, dict)
    ]
    assert top_causes, "Expected ranked top causes"
    assert top_causes[0].get("suspected_source") == "wheel/tire"
    return primary


def assert_localized_wheel_fault_report(
    artifacts: WheelFaultArtifacts,
    *,
    expected_location: str,
    primary_finding: dict,
) -> None:
    report_text = pdf_text(artifacts.pdf_bytes)
    report_text_normalized = normalize_location(report_text)
    assert "what to do next" in report_text
    assert re.search(r"(?:most\s+)?likely source\s+wheel / tire", report_text)
    assert expected_location in report_text_normalized
    assert not re.search(r"(?:most\s+)?likely source\s+driveline", report_text)
    assert not re.search(r"(?:most\s+)?likely source\s+engine", report_text)
    _validate_pdf_report(artifacts.pdf_bytes, primary_finding)


def assert_localized_wheel_fault_alignment(artifacts: WheelFaultArtifacts) -> None:
    _validate_primary_finding_consistency(artifacts.run_analysis, artifacts.insights)
    _validate_bucket_distribution(artifacts.run_analysis, artifacts.export_samples)
    _validate_graph_spikes(artifacts.run_analysis, artifacts.export_samples)
    _validate_primary_finding_vs_graph(artifacts.run_analysis)


def cleanup_localized_wheel_fault_run(base_url: str, run_id: str | None) -> None:
    cleanup_steps = [
        ("stop recording", lambda: api_json(base_url, "/api/recording/stop", method="POST")),
        ("cleanup simulator clients", lambda: _cleanup_clients(base_url)),
    ]
    if run_id is not None:
        cleanup_steps.insert(1, ("cleanup run", lambda rid=run_id: _cleanup_run(base_url, rid)))
    run_cleanup_steps(*cleanup_steps)


def _parse_csv_value(value: str) -> object:
    text = value.strip()
    if text == "":
        return text
    if text == "None":
        return None
    if text in {"True", "False"}:
        return text == "True"
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return text
    try:
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except ValueError:
        return text


def _fft_entry(entry: object) -> tuple[float, float]:
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return float(entry[0]), float(entry[1])
    if isinstance(entry, dict):
        hz = float(entry.get("hz") or entry.get("freq_hz") or 0)
        amp = float(entry.get("amp") or entry.get("amplitude") or 0)
        return hz, amp
    raise ValueError(f"Unrecognised fft_spectrum entry shape: {entry!r}")


def _location_label(sample: dict) -> str:
    client_name = str(sample.get("client_name") or "").strip()
    if client_name:
        return client_name
    client_id = str(sample.get("client_id") or "").strip()
    return f"Sensor {client_id[-4:]}" if client_id else "Unlabeled sensor"


def _compute_fft_from_samples(
    samples: list[dict],
    *,
    freq_bin_hz: float = 2.0,
) -> list[tuple[float, float]]:
    bins: dict[float, float] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        top_peaks = sample.get("top_peaks")
        if not isinstance(top_peaks, list):
            continue
        for peak in top_peaks[:8]:
            if not isinstance(peak, dict):
                continue
            try:
                hz = float(peak.get("hz") or 0)
                amp = float(peak.get("amp") or 0)
            except (TypeError, ValueError):
                continue
            if hz <= 0 or amp <= 0:
                continue
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = bin_low + (freq_bin_hz / 2.0)
            if amp > bins.get(bin_center, 0.0):
                bins[bin_center] = amp
    return sorted(bins.items(), key=lambda item: item[0])


def _compute_bucket_dist_from_samples(samples: list[dict]) -> dict[str, dict]:
    counts: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)

        try:
            vib_raw = sample.get("vibration_strength_db")
            if vib_raw is None:
                continue
            vib = float(vib_raw)
            if math.isnan(vib):
                continue
        except (TypeError, ValueError):
            continue

        bucket = str(sample.get("strength_bucket") or "")
        if not bucket:
            continue

        if location not in counts:
            counts[location] = {f"l{i}": 0 for i in range(1, 6)}
            totals[location] = 0

        if bucket in counts[location]:
            counts[location][bucket] += 1
            totals[location] += 1

    result: dict[str, dict] = {}
    for location, loc_counts in counts.items():
        total = totals[location]
        dist: dict = {"total": total, "counts": dict(loc_counts)}
        for i in range(1, 6):
            key = f"l{i}"
            dist[f"percent_time_{key}"] = (loc_counts[key] / total * 100.0) if total > 0 else 0.0
        result[location] = dist
    return result


def _compute_p95_by_location(samples: list[dict]) -> dict[str, float]:
    vals_by_loc: dict[str, list[float]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)
        try:
            value = float(sample.get("vibration_strength_db") or float("nan"))
            if math.isnan(value) or value < 0:
                continue
        except (TypeError, ValueError):
            continue
        vals_by_loc.setdefault(location, []).append(value)

    result: dict[str, float] = {}
    for location, values in vals_by_loc.items():
        if values:
            result[location] = percentile(sorted(values), 0.95)
    return result


def _primary_matched_hz(finding: dict, plots: dict) -> float | None:
    matched_points = finding.get("matched_points")
    if isinstance(matched_points, list):
        hz_vals = []
        for pt in matched_points:
            if not isinstance(pt, dict):
                continue
            try:
                value = float(pt.get("matched_hz") or 0)
                if value > 0:
                    hz_vals.append(value)
            except (TypeError, ValueError):
                continue
        if hz_vals:
            hz_vals.sort()
            return hz_vals[len(hz_vals) // 2]

    label = str(finding.get("frequency_hz_or_order") or "")
    for entry in plots.get("freq_vs_speed_by_finding", []):
        if not isinstance(entry, dict) or str(entry.get("label", "")) != label:
            continue
        matched = entry.get("matched", [])
        if not isinstance(matched, list):
            continue
        hz_vals = []
        for pt in matched:
            try:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    value = float(pt[1])
                elif isinstance(pt, dict):
                    value = float(pt.get("matched_hz") or pt.get("hz") or 0)
                else:
                    continue
                if value > 0:
                    hz_vals.append(value)
            except (TypeError, ValueError):
                continue
        if hz_vals:
            hz_vals.sort()
            return hz_vals[len(hz_vals) // 2]

    return None


def _pdf_normalized(pdf_bytes: bytes) -> str:
    text = pdf_text(pdf_bytes)
    text = text.replace("\u00d7", "x")
    return re.sub(r"\s+", " ", text)


def _validate_primary_finding_consistency(
    run_analysis: dict,
    insights: dict,
) -> None:
    run_findings = non_ref_findings(run_analysis)
    ins_findings = non_ref_findings(insights)
    assert run_findings, "[cross-source] run.analysis has no non-reference findings"
    assert ins_findings, "[cross-source] insights has no non-reference findings"

    run_pf = run_findings[0]
    ins_pf = ins_findings[0]

    assert run_pf.get("suspected_source") == ins_pf.get("suspected_source"), (
        f"[cross-source] suspected_source mismatch: "
        f"run={run_pf.get('suspected_source')!r} insights={ins_pf.get('suspected_source')!r}"
    )
    assert normalize_location(str(run_pf.get("strongest_location") or "")) == (
        normalize_location(str(ins_pf.get("strongest_location") or ""))
    ), (
        f"[cross-source] strongest_location mismatch: "
        f"run={run_pf.get('strongest_location')!r} insights={ins_pf.get('strongest_location')!r}"
    )
    assert str(run_pf.get("frequency_hz_or_order") or "").strip() == (
        str(ins_pf.get("frequency_hz_or_order") or "").strip()
    ), (
        f"[cross-source] frequency_hz_or_order mismatch: "
        f"run={run_pf.get('frequency_hz_or_order')!r} "
        f"insights={ins_pf.get('frequency_hz_or_order')!r}"
    )


def _validate_bucket_distribution(
    run_analysis: dict,
    samples: list[dict],
) -> None:
    computed = _compute_bucket_dist_from_samples(samples)
    analysis_rows = [
        row for row in run_analysis.get("sensor_intensity_by_location", []) if isinstance(row, dict)
    ]

    for row in analysis_rows:
        location = str(row.get("location") or "")
        dist = row.get("strength_bucket_distribution")
        if not isinstance(dist, dict):
            continue

        assert location in computed, (
            f"[bucket] analysis location {location!r} not found in computed export "
            f"(computed locations: {sorted(computed)})"
        )
        comp = computed[location]

        assert dist["total"] == comp["total"], (
            f"[bucket] {location!r} total mismatch: "
            f"analysis={dist['total']} computed={comp['total']}"
        )

        analysis_counts = dist.get("counts", {})
        comp_counts = comp["counts"]
        for i in range(1, 6):
            key = f"l{i}"
            assert int(analysis_counts.get(key) or 0) == int(comp_counts.get(key) or 0), (
                f"[bucket] {location!r} counts[{key}] mismatch: "
                f"analysis={analysis_counts.get(key)} computed={comp_counts.get(key)}"
            )

        total = dist["total"]
        if total > 0:
            for i in range(1, 6):
                key = f"l{i}"
                analysis_pct = float(dist.get(f"percent_time_{key}") or 0.0)
                expected_pct = int(analysis_counts.get(key) or 0) / total * 100.0
                assert abs(analysis_pct - expected_pct) < 0.01, (
                    f"[bucket] {location!r} percent_time_{key} mismatch: "
                    f"analysis={analysis_pct:.4f} expected={expected_pct:.4f}"
                )

    p95_by_loc = _compute_p95_by_location(samples)
    if not p95_by_loc:
        return

    strongest_by_p95 = max(p95_by_loc, key=lambda key: p95_by_loc[key])

    run_findings = non_ref_findings(run_analysis)
    if run_findings and analysis_rows:
        primary_location = str(run_findings[0].get("strongest_location") or "")
        observed_locations = {
            normalize_location(str(row.get("location") or "")) for row in analysis_rows
        }
        assert normalize_location(primary_location) in observed_locations, (
            f"[bucket] primary finding strongest_location={primary_location!r} not present "
            f"in sensor_intensity_by_location rows={sorted(observed_locations)!r}"
        )

    if analysis_rows:
        first_location = str(analysis_rows[0].get("location") or "")
        assert normalize_location(first_location) == normalize_location(strongest_by_p95), (
            f"[bucket] sensor_intensity_by_location[0]={first_location!r} "
            f"expected strongest={strongest_by_p95!r} (by p95)"
        )


def _validate_graph_spikes(
    run_analysis: dict,
    samples: list[dict],
) -> None:
    plots = run_analysis.get("plots", {})
    raw_fft = plots.get("fft_spectrum_raw") or plots.get("fft_spectrum", [])
    if not raw_fft:
        return

    analysis_fft: list[tuple[float, float]] = []
    for entry in raw_fft:
        try:
            hz, amp = _fft_entry(entry)
            if hz > 0 and amp > 0:
                analysis_fft.append((hz, amp))
        except (ValueError, IndexError, TypeError):
            continue

    if not analysis_fft:
        return

    computed_fft = _compute_fft_from_samples(samples)
    computed_map = {hz: amp for hz, amp in computed_fft}

    top_analysis = sorted(analysis_fft, key=lambda item: item[1], reverse=True)[:8]
    for hz, analysis_amp in top_analysis:
        assert hz in computed_map, (
            f"[graph] analysis fft bin_center={hz} Hz not found in computed spectrum "
            f"(computed bin centers: {sorted(computed_map)})"
        )
        comp_amp = computed_map[hz]
        if comp_amp > 1e-9:
            rel_err = abs(analysis_amp - comp_amp) / comp_amp
            assert rel_err <= 0.20, (
                f"[graph] amplitude mismatch at {hz} Hz: "
                f"analysis={analysis_amp:.6f} computed={comp_amp:.6f} "
                f"relative_error={rel_err:.2%} (tolerance=20%)"
            )


def _validate_primary_finding_vs_graph(run_analysis: dict) -> None:
    run_findings = non_ref_findings(run_analysis)
    if not run_findings:
        return

    primary = run_findings[0]
    plots = run_analysis.get("plots", {})

    primary_matched_hz = _primary_matched_hz(primary, plots)
    if primary_matched_hz is None or primary_matched_hz <= 0:
        return

    top_spike_hz: float | None = None
    peaks_table = plots.get("peaks_table", [])
    if peaks_table and isinstance(peaks_table[0], dict):
        raw = peaks_table[0].get("frequency_hz")
        try:
            value = float(raw or 0)
            if value > 0:
                top_spike_hz = value
        except (TypeError, ValueError):
            pass

    if top_spike_hz is None:
        best_amp = -1.0
        for entry in plots.get("fft_spectrum", []):
            try:
                hz, amp = _fft_entry(entry)
                if amp > best_amp:
                    best_amp = amp
                    top_spike_hz = hz
            except (ValueError, IndexError, TypeError):
                continue

    if top_spike_hz is None or top_spike_hz <= 0:
        return

    tol = max(1.0, abs(primary_matched_hz) * 0.10)
    harmonic_candidates = [primary_matched_hz, primary_matched_hz / 2.0, primary_matched_hz * 2.0]
    best_delta = min(abs(top_spike_hz - candidate_hz) for candidate_hz in harmonic_candidates)
    assert best_delta <= tol, (
        f"[graph-vs-finding] top spike={top_spike_hz:.2f} Hz far from "
        f"primary finding matched_hz={primary_matched_hz:.2f} Hz "
        f"(or its 0.5x/2x harmonic; tolerance={tol:.2f} Hz)"
    )


def _validate_pdf_report(pdf_bytes: bytes, primary_finding: dict) -> None:
    pdf = _pdf_normalized(pdf_bytes)

    assert "wheel / tire" in pdf or "wheel/tire" in pdf, (
        "[pdf] primary suspected_source ('wheel / tire') not found in PDF"
    )

    location_raw = str(primary_finding.get("strongest_location") or "")
    if location_raw:
        loc_normalized = normalize_location(location_raw)
        assert loc_normalized in pdf or location_raw.lower() in pdf, (
            f"[pdf] strongest_location {location_raw!r} not found in PDF"
        )

    freq_label_raw = str(primary_finding.get("frequency_hz_or_order") or "").strip()
    freq_label = re.sub(r"\s+", " ", freq_label_raw.lower().replace("\u00d7", "x"))

    if "wheel order" in freq_label:
        assert "wheel order" in pdf, (
            f"[pdf] 'wheel order' not found in PDF (finding label: {freq_label_raw!r})"
        )
    if "engine order" in freq_label:
        assert "engine order" in pdf, (
            f"[pdf] 'engine order' not found in PDF (finding label: {freq_label_raw!r})"
        )
    for token in re.findall(r"\d+x", freq_label):
        assert token in pdf, (
            f"[pdf] multiplier token {token!r} not found in PDF (finding label: {freq_label_raw!r})"
        )
