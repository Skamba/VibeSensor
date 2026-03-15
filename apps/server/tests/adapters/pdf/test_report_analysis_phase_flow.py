from __future__ import annotations

from unittest.mock import patch

import pytest
from test_support.report_helpers import analysis_metadata as _make_metadata
from test_support.report_helpers import analysis_sample as _make_sample
from test_support.report_helpers import (
    call_build_order_findings,
    make_order_finding_samples,
    patch_order_hypothesis,
    wheel_metadata,
)

from vibesensor.infra.config.analysis_settings import wheel_hz_from_speed_kmh
from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.use_cases.diagnostics.findings import _build_findings as _findings_build_findings
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase, segment_run_phases


@pytest.mark.parametrize(
    ("phases", "expected_dominant_phase"),
    [
        pytest.param([DrivingPhase.ACCELERATION] * 20, "acceleration", id="with_phases"),
        pytest.param(None, None, id="without_phases"),
    ],
)
def test_build_order_findings_dominant_phase(
    monkeypatch: pytest.MonkeyPatch,
    phases,
    expected_dominant_phase: str | None,
) -> None:
    patch_order_hypothesis(monkeypatch)
    samples = [
        {
            "t_s": float(i),
            "speed_kmh": 40.0 + float(i),
            "strength_floor_amp_g": 0.001,
            "top_peaks": [{"hz": 5.0, "amp": 0.05}],
            "location": "front_left",
        }
        for i in range(20)
    ]
    findings = call_build_order_findings(samples, per_sample_phases=phases)
    assert len(findings) == 1
    assert findings[0].get("dominant_phase") == expected_dominant_phase


def test_build_order_findings_per_phase_confidence_key_present() -> None:
    speed_kmh = 70.0
    wh = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
    findings = call_build_order_findings(
        make_order_finding_samples(20, speed_kmh, wh),
        per_sample_phases=[DrivingPhase.CRUISE] * 20,
        speed_stddev_kmh=5.0,
        engine_ref_sufficient=False,
    )
    assert findings
    evidence_metrics = findings[0].get("evidence_metrics") or {}
    assert "per_phase_confidence" in evidence_metrics
    assert "phases_with_evidence" in evidence_metrics
    per_phase_confidence = evidence_metrics["per_phase_confidence"]
    assert isinstance(per_phase_confidence, dict)
    assert "cruise" in per_phase_confidence
    assert evidence_metrics["phases_with_evidence"] >= 1


def test_build_order_findings_no_phases_leaves_per_phase_confidence_none() -> None:
    speed_kmh = 70.0
    wh = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
    findings = call_build_order_findings(
        make_order_finding_samples(20, speed_kmh, wh),
        speed_stddev_kmh=5.0,
        engine_ref_sufficient=False,
    )
    assert findings
    evidence_metrics = findings[0].get("evidence_metrics") or {}
    assert evidence_metrics.get("per_phase_confidence") is None
    assert evidence_metrics.get("phases_with_evidence") == 0


def test_build_order_findings_multi_phase_higher_confidence_than_single_phase() -> None:
    speed_kmh = 70.0
    wh = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
    samples = make_order_finding_samples(20, speed_kmh, wh)

    single_findings = call_build_order_findings(
        samples,
        per_sample_phases=[DrivingPhase.CRUISE] * 20,
        speed_stddev_kmh=5.0,
        engine_ref_sufficient=False,
    )
    multi_findings = call_build_order_findings(
        samples,
        per_sample_phases=[DrivingPhase.CRUISE] * 10 + [DrivingPhase.ACCELERATION] * 10,
        speed_stddev_kmh=5.0,
        engine_ref_sufficient=False,
    )

    assert single_findings
    assert multi_findings
    conf_single = float(single_findings[0].get("confidence") or 0.0)
    conf_multi = float(multi_findings[0].get("confidence") or 0.0)
    assert conf_multi >= conf_single
    assert (multi_findings[0].get("evidence_metrics") or {}).get("phases_with_evidence", 0) >= 2


def test_build_findings_per_phase_confidence_flows_through_pipeline() -> None:
    samples = []
    for idx in range(30):
        speed_kmh = 50.0 + float(idx)
        wh = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        samples.append(
            {
                "t_s": float(idx),
                "speed_kmh": speed_kmh,
                "vibration_strength_db": 30.0,
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wh, "amp": 0.05}],
                "location": "front_left",
            },
        )

    findings = (
        summarize_run_data(
            wheel_metadata(),
            samples,
            include_samples=False,
        ).get("findings")
        or []
    )
    order_findings = [
        finding for finding in findings if str(finding.get("finding_id") or "") == "F_ORDER"
    ]
    if order_findings:
        evidence_metrics = order_findings[0].get("evidence_metrics") or {}
        assert "per_phase_confidence" in evidence_metrics
        assert "phases_with_evidence" in evidence_metrics


def test_build_findings_accepts_per_sample_phases_without_recomputing() -> None:
    samples = [_make_sample(float(i) * 0.5, 60.0, 0.02) for i in range(20)]
    pre_computed_phases, _ = segment_run_phases(samples)
    recompute_calls: list[int] = []

    def _patched_segment_run_phases(sequence):
        recompute_calls.append(1)
        return segment_run_phases(sequence)

    with patch(
        "vibesensor.use_cases.diagnostics.findings.segment_run_phases",
        side_effect=_patched_segment_run_phases,
    ):
        _findings_build_findings(
            metadata={"units": {"accel_x_g": "g"}},
            samples=samples,
            speed_sufficient=True,
            steady_speed=False,
            speed_stddev_kmh=None,
            speed_non_null_pct=100.0,
            raw_sample_rate_hz=200.0,
            lang="en",
            per_sample_phases=pre_computed_phases,
        )

    assert recompute_calls == []


def test_summarize_run_data_passes_phases_to_build_findings() -> None:
    metadata = _make_metadata()
    samples = [
        {
            "t_s": float(i) * 0.5,
            "speed_kmh": 0.0 if i < 5 else 60.0,
            "accel_x_g": 0.01,
            "accel_y_g": 0.01,
            "accel_z_g": 0.01,
            "vibration_strength_db": 15.0,
            "strength_bucket": "l1",
        }
        for i in range(20)
    ]
    recompute_calls: list[int] = []

    def _patched_srp(sequence):
        recompute_calls.append(1)
        return segment_run_phases(sequence)

    patch_target = "vibesensor.use_cases.diagnostics.findings.segment_run_phases"
    with patch(patch_target, side_effect=_patched_srp):
        summary = summarize_run_data(metadata, samples, include_samples=False)

    assert "findings" in summary
    assert recompute_calls == []
