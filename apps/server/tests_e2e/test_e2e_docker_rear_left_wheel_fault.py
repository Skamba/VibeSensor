from __future__ import annotations

import ast
import csv
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import zipfile
from math import floor
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _api(base_url: str, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _api_bytes(base_url: str, path: str) -> tuple[bytes, str]:
    req = Request(f"{base_url}{path}")
    with urlopen(req, timeout=30) as resp:
        return resp.read(), str(resp.headers.get("Content-Type", ""))


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(filter(None, (page.extract_text() for page in reader.pages))).lower()


# ---------------------------------------------------------------------------
# Parsing and aggregation helpers used by validation functions
# ---------------------------------------------------------------------------


def _normalize_location(s: str) -> str:
    """Lowercase and collapse whitespace/hyphens/underscores to a single space."""
    return re.sub(r"[\s\-_]+", " ", str(s).strip().lower())


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


def _parse_export_zip(raw: bytes) -> tuple[dict, list[dict]]:
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        names = archive.namelist()
        json_name = next(name for name in names if name.endswith(".json"))
        csv_name = next(name for name in names if name.endswith("_raw.csv"))
        metadata = json.loads(archive.read(json_name).decode("utf-8"))
        reader = csv.DictReader(io.StringIO(archive.read(csv_name).decode("utf-8")))
        samples = [{k: _parse_csv_value(v) for k, v in row.items()} for row in reader]
    return metadata, samples


def _fft_entry(entry: object) -> tuple[float, float]:
    """Parse one fft_spectrum entry to (hz, amp) regardless of list/dict shape."""
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return float(entry[0]), float(entry[1])
    if isinstance(entry, dict):
        hz = float(entry.get("hz") or entry.get("freq_hz") or 0)
        amp = float(entry.get("amp") or entry.get("amplitude") or 0)
        return hz, amp
    raise ValueError(f"Unrecognised fft_spectrum entry shape: {entry!r}")


def _location_label(sample: dict) -> str:
    """Mirror server's _location_label helper (helpers.py)."""
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
    """Mirror server's _aggregate_fft_spectrum (plot_data.py) for independent validation."""
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
    """Compute per-location bucket distribution from raw samples.

    Mirrors the counting logic in findings._sensor_intensity_by_location:
    - only samples where vibration_strength_db is non-null are considered
    - only samples with a non-empty strength_bucket contribute to counts
    """
    counts: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)

        # Mirror server: skip if vibration_strength_db is missing/non-numeric
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
            continue  # missing bucket: not counted (mirrors server logic)

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
    """Compute p95 of vibration_strength_db per location, ignoring None/negative values."""
    vals_by_loc: dict[str, list[float]] = {}
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample)
        try:
            v = float(sample.get("vibration_strength_db") or float("nan"))
            if math.isnan(v) or v < 0:
                continue
        except (TypeError, ValueError):
            continue
        vals_by_loc.setdefault(location, []).append(v)

    result: dict[str, float] = {}
    for loc, vals in vals_by_loc.items():
        if vals:
            sv = sorted(vals)
            idx = max(0, int(math.ceil(len(sv) * 0.95)) - 1)
            result[loc] = sv[idx]
    return result


def _primary_matched_hz(finding: dict, plots: dict) -> float | None:
    """Extract a representative matched Hz from the primary finding.

    Preferred: median of all matched_hz > 0 in finding.matched_points.
    Fallback: median of matched hz values in plots.freq_vs_speed_by_finding
              for the entry whose label matches frequency_hz_or_order.
    Returns None if no positive matched Hz values are found.
    """
    # Preferred: from finding.matched_points
    matched_points = finding.get("matched_points")
    if isinstance(matched_points, list):
        hz_vals = []
        for pt in matched_points:
            if not isinstance(pt, dict):
                continue
            try:
                v = float(pt.get("matched_hz") or 0)
                if v > 0:
                    hz_vals.append(v)
            except (TypeError, ValueError):
                continue
        if hz_vals:
            hz_vals.sort()
            return hz_vals[len(hz_vals) // 2]

    # Fallback: from freq_vs_speed_by_finding
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
                    v = float(pt[1])
                elif isinstance(pt, dict):
                    v = float(pt.get("matched_hz") or pt.get("hz") or 0)
                else:
                    continue
                if v > 0:
                    hz_vals.append(v)
            except (TypeError, ValueError):
                continue
        if hz_vals:
            hz_vals.sort()
            return hz_vals[len(hz_vals) // 2]

    return None


def _pdf_normalized(pdf_bytes: bytes) -> str:
    """Extract PDF text, lower-case, normalise Unicode multiply sign and whitespace."""
    text = _pdf_text(pdf_bytes)  # already lower-cased
    text = text.replace("\u00d7", "x")  # × → x
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def _validate_primary_finding_consistency(
    run_analysis: dict,
    insights: dict,
) -> None:
    """Validation 1 – primary finding fields must agree across run.analysis and insights.

    Asserts that suspected_source, strongest_location, and frequency_hz_or_order
    are identical in both payloads for the first non-reference finding.
    """
    run_findings = [
        f
        for f in run_analysis.get("findings", [])
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]
    ins_findings = [
        f
        for f in insights.get("findings", [])
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]
    assert run_findings, "[cross-source] run.analysis has no non-reference findings"
    assert ins_findings, "[cross-source] insights has no non-reference findings"

    run_pf = run_findings[0]
    ins_pf = ins_findings[0]

    assert run_pf.get("suspected_source") == ins_pf.get("suspected_source"), (
        f"[cross-source] suspected_source mismatch: "
        f"run={run_pf.get('suspected_source')!r} insights={ins_pf.get('suspected_source')!r}"
    )
    assert _normalize_location(str(run_pf.get("strongest_location") or "")) == (
        _normalize_location(str(ins_pf.get("strongest_location") or ""))
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
    """Validation 2 – bucket distribution in analysis must match raw exported samples.

    Also asserts that:
    - The sensor with highest p95 vibration_strength_db from raw samples matches
      the primary finding's strongest_location.
    - sensor_intensity_by_location[0] is ordered by highest p95/max (the strongest sensor).
    """
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

    # Verify strongest location ordering by raw p95
    p95_by_loc = _compute_p95_by_location(samples)
    if not p95_by_loc:
        return

    strongest_by_p95 = max(p95_by_loc, key=lambda k: p95_by_loc[k])

    run_findings = [
        f
        for f in run_analysis.get("findings", [])
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]
    if run_findings:
        primary_location = str(run_findings[0].get("strongest_location") or "")
        assert _normalize_location(strongest_by_p95) == _normalize_location(primary_location), (
            f"[bucket] strongest_location_by_p95={strongest_by_p95!r} does not match "
            f"primary finding strongest_location={primary_location!r}"
        )

    if analysis_rows:
        first_location = str(analysis_rows[0].get("location") or "")
        assert _normalize_location(first_location) == _normalize_location(strongest_by_p95), (
            f"[bucket] sensor_intensity_by_location[0]={first_location!r} "
            f"expected strongest={strongest_by_p95!r} (by p95)"
        )


def _validate_graph_spikes(
    run_analysis: dict,
    samples: list[dict],
) -> None:
    """Validation 3 – fft_spectrum_raw in analysis is consistent with raw sample top_peaks.

    Computes an independent max-amplitude FFT spectrum from exported samples using
    the same 2 Hz binning algorithm as the server, then verifies the top-8 analysis
    bins exist in the computed spectrum with amplitude within 20% relative tolerance.
    Uses fft_spectrum_raw (max-amplitude) rather than fft_spectrum (persistence-weighted).
    """
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

    # Compare top 8 analysis bins by amplitude against computed
    top_analysis = sorted(analysis_fft, key=lambda x: x[1], reverse=True)[:8]
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
    """Validation 4 – primary finding's matched frequency aligns with the top graph spike.

    The top-amplitude spike in the peaks_table (or fft_spectrum as fallback) must be
    within max(1.0 Hz, 10% relative) of the median matched_hz in the primary finding.
    """
    run_findings = [
        f
        for f in run_analysis.get("findings", [])
        if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
    ]
    if not run_findings:
        return

    primary = run_findings[0]
    plots = run_analysis.get("plots", {})

    primary_matched_hz = _primary_matched_hz(primary, plots)
    if primary_matched_hz is None or primary_matched_hz <= 0:
        return  # No usable matched Hz – skip rather than false-fail

    # Extract top spike frequency: prefer peaks_table[0], fall back to fft_spectrum max
    top_spike_hz: float | None = None
    peaks_table = plots.get("peaks_table", [])
    if peaks_table and isinstance(peaks_table[0], dict):
        raw = peaks_table[0].get("frequency_hz")
        try:
            v = float(raw or 0)
            if v > 0:
                top_spike_hz = v
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
    assert abs(top_spike_hz - primary_matched_hz) <= tol, (
        f"[graph-vs-finding] top spike={top_spike_hz:.2f} Hz far from "
        f"primary finding matched_hz={primary_matched_hz:.2f} Hz "
        f"(tolerance={tol:.2f} Hz)"
    )


def _validate_pdf_report(pdf_bytes: bytes, primary_finding: dict) -> None:
    """Validation 5 – PDF report must reflect the primary finding's key attributes.

    Checks suspected_source human label, strongest_location, and the order noun-phrase
    (e.g. 'wheel order') plus any multiplier tokens (e.g. '1x') from the finding label.
    """
    pdf = _pdf_normalized(pdf_bytes)

    # --- suspected source ---
    assert "wheel / tire" in pdf or "wheel/tire" in pdf, (
        "[pdf] primary suspected_source ('wheel / tire') not found in PDF"
    )

    # --- strongest location (rear-left) ---
    location_raw = str(primary_finding.get("strongest_location") or "")
    if location_raw:
        loc_normalized = _normalize_location(location_raw)
        assert loc_normalized in pdf or location_raw.lower() in pdf, (
            f"[pdf] strongest_location {location_raw!r} not found in PDF"
        )

    # --- frequency/order label ---
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
    # Check multiplier tokens like "1x", "2x", "3x" etc.
    for token in re.findall(r"\d+x", freq_label):
        assert token in pdf, (
            f"[pdf] multiplier token {token!r} not found in PDF (finding label: {freq_label_raw!r})"
        )


# ---------------------------------------------------------------------------
# Main E2E test
# ---------------------------------------------------------------------------


def test_e2e_docker_rear_left_wheel_fault() -> None:
    base_url = os.environ["VIBESENSOR_BASE_URL"]
    sim_host = os.environ["VIBESENSOR_SIM_SERVER_HOST"]
    sim_data_port = os.environ["VIBESENSOR_SIM_DATA_PORT"]
    sim_control_port = os.environ["VIBESENSOR_SIM_CONTROL_PORT"]
    sim_duration = os.environ["VIBESENSOR_SIM_DURATION"]
    sim_log_path = Path(os.environ["VIBESENSOR_SIM_LOG"])

    history_before = _api(base_url, "/api/history")
    assert history_before["runs"] == [], "Expected empty history before E2E run"

    _api(base_url, "/api/settings/speed-source", method="POST", body={"speedSource": "manual", "manualSpeedKph": 100.0})
    start = _api(base_url, "/api/logging/start", method="POST")
    assert start["enabled"] is True

    sim_cmd = [
        sys.executable,
        str(ROOT / "apps" / "simulator" / "sim_sender.py"),
        "--server-host",
        sim_host,
        "--server-data-port",
        sim_data_port,
        "--server-control-port",
        sim_control_port,
        "--server-http-port",
        base_url.rsplit(":", 1)[-1],
        "--count",
        "4",
        "--names",
        "front-left,front-right,rear-left,rear-right",
        "--scenario",
        "one-wheel-mild",
        "--fault-wheel",
        "rear-left",
        "--speed-kmh",
        "0",
        "--duration",
        sim_duration,
        "--no-auto-server",
        "--no-interactive",
    ]
    with sim_log_path.open("w", encoding="utf-8") as sim_log:
        subprocess.run(sim_cmd, cwd=str(ROOT), check=True, stdout=sim_log, stderr=subprocess.STDOUT)

    _api(base_url, "/api/logging/stop", method="POST")

    deadline = time.monotonic() + 40.0
    run_id = None
    while time.monotonic() < deadline:
        history_after = _api(base_url, "/api/history")
        if len(history_after["runs"]) == 1 and history_after["runs"][0]["status"] == "complete":
            run_id = str(history_after["runs"][0]["run_id"])
            break
        time.sleep(1.0)
    assert run_id is not None, "Run did not complete in time"

    insights = _api(base_url, f"/api/history/{run_id}/insights")
    findings = [
        f
        for f in insights.get("findings", [])
        if not str(f.get("finding_id", "")).startswith("REF_")
    ]
    assert findings, "Expected non-reference findings"

    primary = findings[0]
    assert primary.get("suspected_source") == "wheel/tire"
    primary_location = str(primary.get("strongest_location") or "").lower()
    assert "rear left" in primary_location or "rear-left" in primary_location
    top_causes = [item for item in insights.get("top_causes", []) if isinstance(item, dict)]
    assert top_causes, "Expected ranked top causes"
    assert top_causes[0].get("source") == "wheel/tire"

    pdf_bytes, content_type = _api_bytes(base_url, f"/api/history/{run_id}/report.pdf?lang=en")
    assert content_type.startswith("application/pdf")
    assert pdf_bytes[:5] == b"%PDF-"
    pdf_text = _pdf_text(pdf_bytes)
    assert "primary system:" in pdf_text
    assert "wheel / tire" in pdf_text
    assert "rear left" in pdf_text or "rear-left" in pdf_text
    assert "primary system: driveline" not in pdf_text
    assert "primary system: engine" not in pdf_text

    # ------------------------------------------------------------------
    # Alignment validation: cross-source consistency checks
    # ------------------------------------------------------------------

    run_payload = _api(base_url, f"/api/history/{run_id}")
    export_bytes, export_content_type = _api_bytes(base_url, f"/api/history/{run_id}/export")
    assert export_content_type.startswith("application/zip")
    _, export_samples = _parse_export_zip(export_bytes)
    run_analysis = run_payload.get("analysis") or {}

    # Validation 1: primary finding consistent across run payload and insights
    _validate_primary_finding_consistency(run_analysis, insights)

    # Validation 2: bucket distribution matches raw exported samples
    _validate_bucket_distribution(run_analysis, export_samples)

    # Validation 3: fft_spectrum bins match independently computed spectrum
    _validate_graph_spikes(run_analysis, export_samples)

    # Validation 4: primary finding matched Hz aligns with top graph spike
    _validate_primary_finding_vs_graph(run_analysis)

    # Validation 5: PDF reflects primary finding source, location, and order label
    _validate_pdf_report(pdf_bytes, primary)
