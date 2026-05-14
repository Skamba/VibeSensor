from __future__ import annotations

import pytest
from test_support.report_helpers import analysis_metadata as _make_metadata
from test_support.report_helpers import analysis_sample as _make_sample
from test_support.report_helpers import (
    call_build_order_findings,
    diagnostics_context,
    patch_order_hypothesis,
    wheel_metadata,
)

from vibesensor.adapters.analysis_summary import build_findings_for_samples
from vibesensor.domain import Finding, LocationHotspot
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.constants.units import KMH_TO_MPS
from vibesensor.use_cases.diagnostics import findings as findings_builder_module
from vibesensor.use_cases.diagnostics._analysis_models import FindingsBuildRequest
from vibesensor.use_cases.diagnostics.findings import _build_findings as _findings_build_findings
from vibesensor.use_cases.diagnostics.location_analysis import LocationAnalysisResult
from vibesensor.use_cases.diagnostics.peaks.table import (
    top_peaks_table_rows as _top_peaks_table_rows,
)
from vibesensor.use_cases.diagnostics.signal_aggregation import _speed_breakdown


def test_speed_breakdown_basic() -> None:
    samples = [
        _make_sample(1.0, 85.0, 0.02),
        _make_sample(2.0, 87.0, 0.03),
        _make_sample(3.0, 92.0, 0.01),
    ]
    rows = _speed_breakdown(sensor_frames_from_mappings(samples))
    assert len(rows) == 2
    labels = [row.speed_range for row in rows]
    assert "80-90 km/h" in labels
    assert "90-100 km/h" in labels


def test_speed_breakdown_uses_fixed_10kmh_bins_at_boundaries() -> None:
    samples = [
        {"speed_kmh": 79.9, "strength_peak_band_rms_amp_g": 0.01},
        {"speed_kmh": 80.1, "strength_peak_band_rms_amp_g": 0.02},
    ]

    rows = _speed_breakdown(sensor_frames_from_mappings(samples))
    labels = {row.speed_range for row in rows}

    assert "70-80 km/h" in labels
    assert "80-90 km/h" in labels


def test_speed_breakdown_empty() -> None:
    assert _speed_breakdown([]) == []


def test_speed_breakdown_no_speed() -> None:
    assert (
        _speed_breakdown(
            sensor_frames_from_mappings([{"speed_kmh": None}, {"speed_kmh": 0}]),
        )
        == []
    )


def test_build_findings_empty_samples() -> None:
    findings = build_findings_for_samples(metadata=_make_metadata(), samples=[], lang="en")
    assert isinstance(findings, tuple)


def test_build_findings_with_speed_data() -> None:
    samples = [_make_sample(float(i) * 0.5, 80.0 + i * 0.5, 0.01 + i * 0.001) for i in range(20)]
    findings = build_findings_for_samples(metadata=_make_metadata(), samples=samples, lang="en")
    assert isinstance(findings, tuple)
    assert findings


def test_build_findings_nl_language() -> None:
    samples = [_make_sample(float(i) * 0.5, 85.0, 0.05) for i in range(10)]
    findings = build_findings_for_samples(metadata=_make_metadata(), samples=samples, lang="nl")
    assert isinstance(findings, tuple)
    assert all(isinstance(finding, Finding) for finding in findings)


def test_build_findings_orders_informational_transients_after_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_order_findings(_request: object) -> list[Finding]:
        return [
            Finding(
                finding_id="F_PEAK",
                severity="diagnostic",
                suspected_source="wheel/tire",
                confidence=0.30,
            ),
        ]

    def _fake_persistent_peaks(**_kwargs) -> list[Finding]:
        return [
            Finding(
                finding_id="F_PEAK",
                severity="info",
                suspected_source="transient_impact",
                peak_classification="transient",
                confidence=0.22,
            ),
        ]

    monkeypatch.setattr(findings_builder_module, "_build_order_findings", _fake_order_findings)
    monkeypatch.setattr(
        findings_builder_module,
        "_build_persistent_peak_findings",
        _fake_persistent_peaks,
    )

    findings = _findings_build_findings(
        FindingsBuildRequest(
            context=diagnostics_context({"units": {"accel_x_g": "g"}}),
            samples=[],
            speed_sufficient=True,
            steady_speed=False,
            speed_stddev_kmh=None,
            speed_non_null_pct=100.0,
            raw_sample_rate_hz=200.0,
            lang="en",
            per_sample_phases=None,
            run_noise_baseline_g=None,
        ),
    )
    non_ref_findings = [
        finding for finding in findings if not finding.finding_id.startswith("REF_")
    ]

    assert len(non_ref_findings) >= 2
    assert non_ref_findings[0].severity != "info"
    assert non_ref_findings[-1].severity == "info"


def test_build_findings_detects_sparse_high_speed_only_fault() -> None:
    samples = []
    for idx in range(30):
        speed_kmh = 40.0 + (2.0 * idx)
        wh = speed_kmh * KMH_TO_MPS / 2.036
        high_speed_band = speed_kmh >= 90.0
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.03 if high_speed_band else 0.01),
                "strength_floor_amp_g": 0.003,
                "top_peaks": [
                    {"hz": wh, "amp": 0.03} if high_speed_band else {"hz": wh + 7.0, "amp": 0.01},
                ],
            },
        )

    findings = build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en")
    wheel_finding = next(
        (finding for finding in findings if finding.finding_key == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    strongest_speed_band = wheel_finding.strongest_speed_band or ""
    assert strongest_speed_band.endswith("km/h")
    low_str, high_str = strongest_speed_band.replace(" km/h", "").split("-", maxsplit=1)
    assert float(low_str) >= 90.0
    assert float(high_str) >= float(low_str)


def test_build_order_findings_min_match_threshold_stays_below_confidence_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_order_hypothesis(monkeypatch, dominance_ratio=1.2)

    samples = []
    for idx in range(16):
        matched = idx < 4
        samples.append(
            {
                "t_s": float(idx),
                "speed_kmh": 40.0 + idx,
                "strength_floor_amp_g": 1000.0,
                "top_peaks": [{"hz": 5.5 if matched else 20.0, "amp": 0.001}],
                "location": "front_left",
            },
        )

    findings = call_build_order_findings(samples)
    assert len(findings) == 1
    finding = findings[0]
    confidence = finding.effective_confidence
    match_rate = finding.evidence.global_match_rate if finding.evidence is not None else 0.0
    assert match_rate == pytest.approx(0.25)
    assert confidence < 0.25


def test_build_findings_order_exposes_structured_speed_profile() -> None:
    samples = []
    for idx in range(24):
        speed_kmh = 60.0 + float(idx)
        wh = speed_kmh * KMH_TO_MPS / 2.036
        amp = 0.01 + (0.0008 * idx)
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, amp),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wh, "amp": amp}],
            },
        )

    findings = build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en")
    wheel_finding = next(
        (finding for finding in findings if finding.finding_key == "wheel_1x"),
        None,
    )
    assert wheel_finding is not None
    assert (wheel_finding.strongest_speed_band or "").endswith("km/h")


def test_build_findings_detects_driveline_2x_order() -> None:
    metadata = {
        key: value for key, value in wheel_metadata().items() if key != "current_gear_ratio"
    }
    samples = []
    for idx in range(24):
        speed_kmh = 55.0 + (2.0 * idx)
        wh = speed_kmh * KMH_TO_MPS / 2.036
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.04),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wh * 3.08 * 2.0, "amp": 0.04}],
            },
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    driveline_2x = next(
        (finding for finding in findings if finding.finding_key == "driveshaft_2x"),
        None,
    )

    assert driveline_2x is not None
    assert str(driveline_2x.suspected_source) == "driveline"
    assert driveline_2x.order == "2x driveshaft"


def test_build_findings_persistent_peak_exposes_structured_speed_profile() -> None:
    metadata = {
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 200.0,
        "units": {"accel_x_g": "g"},
    }
    samples = []
    for idx in range(28):
        speed_kmh = 50.0 + float(idx)
        amp = 0.012 + (0.010 * (1.0 - abs(speed_kmh - 68.0) / 20.0))
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, amp),
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": 73.0, "amp": max(0.004, amp)}],
            },
        )

    findings = build_findings_for_samples(metadata=metadata, samples=samples, lang="en")
    persistent = next(
        (finding for finding in findings if finding.finding_key.startswith("peak_")),
        None,
    )
    assert persistent is not None
    assert (persistent.strongest_speed_band or "").endswith("km/h")


def test_speed_band_semantics_are_aligned_across_findings_and_peak_table() -> None:
    samples = []
    for idx, speed_kmh in enumerate(range(40, 121)):
        speed_val = float(speed_kmh)
        wh = speed_val * KMH_TO_MPS / 2.036
        amp = 0.08 if 75 <= speed_kmh <= 90 else 0.01
        samples.append(
            {
                **_make_sample(float(idx), speed_val, amp),
                "strength_floor_amp_g": 0.003,
                "top_peaks": [{"hz": wh, "amp": amp}, {"hz": 43.0, "amp": amp}],
            },
        )

    findings = build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en")
    wheel_finding = next(
        (finding for finding in findings if finding.finding_key == "wheel_1x"),
        None,
    )
    persistent = next(
        (finding for finding in findings if finding.finding_key.startswith("peak_")),
        None,
    )
    assert wheel_finding is not None
    assert persistent is not None

    order_band = wheel_finding.strongest_speed_band or ""
    persistent_band = persistent.strongest_speed_band or ""
    rows = _top_peaks_table_rows(sensor_frames_from_mappings(samples), top_n=6, freq_bin_hz=1.0)
    target_row = min(rows, key=lambda row: abs(row.frequency_hz - 43.0))
    peak_table_band = str(target_row.typical_speed_band or "")

    assert order_band
    assert persistent_band
    assert peak_table_band and peak_table_band != "-"
    assert order_band == persistent_band == peak_table_band

    low_str, high_str = order_band.replace(" km/h", "").split("-", maxsplit=1)
    low = float(low_str)
    high = float(high_str)
    assert 70.0 <= low <= 90.0
    assert 80.0 <= high <= 100.0
    assert (high - low) <= 20.0


def test_build_findings_passes_focused_speed_band_to_location_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_relevant_speed_bins: list[str] = []

    def _fake_location_summary(
        matches,
        lang,
        relevant_speed_bins=None,
        connected_locations=None,
        **_kwargs,
    ):
        if isinstance(relevant_speed_bins, list):
            seen_relevant_speed_bins.extend(str(item) for item in relevant_speed_bins if item)
        chosen_band = seen_relevant_speed_bins[0] if seen_relevant_speed_bins else "90-100 km/h"
        return (
            "focused location",
            LocationAnalysisResult(
                hotspot=LocationHotspot.from_analysis_inputs(
                    strongest_location="Front Right",
                    dominance_ratio=1.4,
                    localization_confidence=0.8,
                    weak_spatial_separation=False,
                ),
                mean_amp=0.03,
                total_samples=10,
                ambiguous_location=False,
                no_wheel_sensors=False,
                speed_range=chosen_band,
                dominance_ratio=1.4,
                localization_confidence=0.8,
                weak_spatial_separation=False,
                top_location="Front Right",
                second_location=None,
                partial_coverage=False,
                corroborated_by_n_sensors=1,
            ),
        )

    from vibesensor.use_cases.diagnostics.orders import scoring as _order_scoring_module

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        _fake_location_summary,
    )

    samples = []
    for idx in range(30):
        speed_kmh = 40.0 + (2.0 * idx)
        wh = speed_kmh * KMH_TO_MPS / 2.036
        high_speed_band = speed_kmh >= 90.0
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.03 if high_speed_band else 0.01),
                "strength_floor_amp_g": 0.003,
                "top_peaks": [
                    {"hz": wh, "amp": 0.03} if high_speed_band else {"hz": wh + 7.0, "amp": 0.01},
                ],
            },
        )

    findings = build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en")
    wheel_finding = next(
        (finding for finding in findings if finding.finding_key == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    assert seen_relevant_speed_bins
    assert seen_relevant_speed_bins[0] in {"90-100 km/h", "100-110 km/h"}
    assert wheel_finding.strongest_location == "Front Right"
