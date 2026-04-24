"""Projection tests for report document assembly and origin wording."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    RUN_END,
    ambiguous_primary_location_summary,
    minimal_summary,
    recapture_guidance_summary,
    sequential_same_source_summary,
    trunk_primary_guidance_summary,
    write_jsonl,
)
from test_support.report_helpers import report_run_metadata as _run_metadata
from test_support.report_helpers import report_sample as _base_sample

from vibesensor.adapters.analysis_summary import summarize_log
from vibesensor.domain import VibrationOrigin
from vibesensor.shared.boundaries.reporting import (
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.shared.boundaries.summary_fields.finding import finding_from_payload
from vibesensor.shared.boundaries.summary_fields.origin import build_origin_explanation
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.diagnostics.run_analysis import (
    summarize_origin,
)
from vibesensor.use_cases.history.report_document import build_report_document


def _sample(
    idx: int,
    *,
    speed_kmh: float,
    dominant_freq_hz: float,
    peak_amp_g: float,
) -> dict[str, object]:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
    )


def _assert_no_phase_onset(explanation: object) -> None:
    if isinstance(explanation, list):
        assert not any(
            isinstance(part, dict) and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
            for part in explanation
        )
    else:
        assert isinstance(explanation, dict)


def _origin_explanation(origin: VibrationOrigin) -> object:
    return build_origin_explanation(
        source=str(origin.suspected_source),
        speed_band=origin.speed_band or "",
        location=origin.summary_location,
        dominance=origin.dominance_ratio,
        weak=origin.weak_spatial_separation,
        dominant_phase=origin.dominant_phase or "",
    )


def test_build_report_document_basic(tmp_path: Path) -> None:
    run_path = tmp_path / "build_report_document.jsonl"
    records: list[dict[str, object]] = [_run_metadata(tire_circumference_m=2.2)]
    for idx in range(20):
        speed = 50 + idx
        wheel_hz = (speed * (1000.0 / 3600.0)) / 2.2
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09),
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    summary = summarize_log(run_path)

    data = build_report_document(prepare_report_input(summary))
    assert isinstance(data, ReportDocument)
    assert data.title
    assert data.run_datetime
    assert data.observed.primary_system
    assert data.observed.certainty_label
    assert data.observed.certainty_reason


def test_build_report_document_no_top_causes() -> None:
    summary = minimal_summary()
    data = build_report_document(prepare_report_input(summary))
    assert isinstance(data, ReportDocument)
    assert data.system_cards == []
    assert data.certainty_tier_key == "A"
    assert len(data.next_steps) >= 1


def test_build_report_document_surfaces_evidence_snapshot_rows() -> None:
    primary = make_finding_payload(
        finding_id="F_PRIMARY",
        suspected_source="wheel/tire",
        confidence=0.76,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        weak_spatial_separation=True,
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.4,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.09,
            },
        ],
    )
    alternative = make_finding_payload(
        finding_id="F_ALT",
        suspected_source="driveline",
        confidence=0.72,
        strongest_location="Rear Left",
        strongest_speed_band="60-80 km/h",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="evidence-run",
                lang="en",
                metadata={
                    "run_id": "evidence-run",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "start_time_utc": "2026-03-23T07:31:01Z",
                    "sensor_model": "ADXL345",
                    "raw_sample_rate_hz": 800,
                    "feature_interval_s": 0.5,
                    "fft_window_size_samples": 256,
                    "peak_picker_method": "fft",
                    "incomplete_for_order_analysis": False,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                findings=[primary, alternative],
                top_causes=[primary, alternative],
                analysis_metadata={
                    "raw_capture_available": True,
                    "raw_backed_sample_count": 24,
                    "raw_capture_mode": "raw_backed",
                },
            )
        )
    )

    data = build_report_document(prepared)

    assert [row.label for row in data.verdict_page.proof_snapshot_rows] == [
        "Confidence",
        "Evidence basis",
        "Support",
        "Stable frequency",
    ]
    assert "Medium (" in data.verdict_page.proof_snapshot_rows[0].value
    assert "Raw-backed replay" in data.verdict_page.proof_snapshot_rows[1].value
    assert data.verdict_page.proof_snapshot_rows[2].value == "3 supporting windows across 1.5 s"
    assert data.verdict_page.proof_snapshot_rows[3].value == "15.1-15.4 Hz matched band"
    assert [row.label for row in data.appendix_c.evidence_snapshot_rows] == [
        "Confidence",
        "Evidence basis",
        "Support",
        "Stable frequency",
        "Strongest sensors",
        "Caveat",
    ]
    assert data.appendix_c.evidence_snapshot_rows[4].value == "Front-Left (2), Rear-Left (1)"
    assert "driveline" in data.appendix_c.evidence_snapshot_rows[5].value.lower()


def test_build_report_document_focuses_appendix_c_on_primary_proof_windows() -> None:
    primary = make_finding_payload(
        finding_id="F_PRIMARY_PROOF",
        suspected_source="wheel/tire",
        confidence=0.79,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x wheel order",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.3,
                "matched_hz": 15.4,
                "location": "Rear Left",
                "phase": "decel",
                "amp": 0.09,
            },
        ],
    )
    alternative = make_finding_payload(
        finding_id="F_ALT_PROOF",
        suspected_source="driveline",
        confidence=0.71,
        strongest_location="Rear Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x driveshaft",
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="appendix-c-proof-run",
                lang="en",
                metadata={
                    "run_id": "appendix-c-proof-run",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "start_time_utc": "2026-03-23T07:31:01Z",
                    "sensor_model": "ADXL345",
                    "raw_sample_rate_hz": 800,
                    "feature_interval_s": 0.5,
                    "fft_window_size_samples": 256,
                    "peak_picker_method": "fft",
                    "incomplete_for_order_analysis": False,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                findings=[primary, alternative],
                top_causes=[primary, alternative],
                analysis_metadata={
                    "raw_capture_available": True,
                    "raw_backed_sample_count": 24,
                    "raw_capture_mode": "raw_backed",
                },
            )
        )
    )

    data = build_report_document(prepared)

    assert len(data.appendix_c.evidence_chain_rows) == 1
    assert data.appendix_c.evidence_chain_rows[0].source_name.startswith("Wheel / Tire")
    assert data.appendix_c.measurement_rows == []
    assert [row.window_id for row in data.appendix_c.proof_window_rows] == ["W01", "W02", "W03"]
    assert data.appendix_c.proof_window_rows[0].dominant_location == "Front Left"
    assert data.appendix_c.proof_window_rows[2].phase == "Decel"


def test_build_report_document_uses_supporting_window_location_proof_in_appendix_b() -> None:
    primary = make_finding_payload(
        finding_id="F_LOCATION_PROOF",
        suspected_source="wheel/tire",
        confidence=0.81,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        matched_points=[
            {
                "t_s": 1.0,
                "speed_kmh": 64.0,
                "predicted_hz": 15.0,
                "matched_hz": 15.1,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.11,
            },
            {
                "t_s": 1.5,
                "speed_kmh": 66.0,
                "predicted_hz": 15.2,
                "matched_hz": 15.2,
                "location": "Front Left",
                "phase": "cruise",
                "amp": 0.10,
            },
            {
                "t_s": 2.0,
                "speed_kmh": 68.0,
                "predicted_hz": 15.4,
                "matched_hz": 15.3,
                "location": "Rear Left",
                "phase": "cruise",
                "amp": 0.03,
            },
        ],
    )
    prepared = prepare_persisted_report_input(
        PersistedAnalysis.from_json_object(
            minimal_summary(
                run_id="appendix-b-location-proof-run",
                lang="en",
                metadata={
                    "run_id": "appendix-b-location-proof-run",
                    "record_type": "metadata",
                    "schema_version": "v2-jsonl",
                    "start_time_utc": "2026-03-23T07:31:01Z",
                    "sensor_model": "ADXL345",
                    "raw_sample_rate_hz": 800,
                    "feature_interval_s": 0.5,
                    "fft_window_size_samples": 256,
                    "peak_picker_method": "fft",
                    "incomplete_for_order_analysis": False,
                },
                sensor_count_used=2,
                sensor_locations=["Front Left", "Rear Left"],
                sensor_locations_connected_throughout=["Front Left", "Rear Left"],
                sensor_intensity_by_location=[
                    {"location": "Front Left", "p95_intensity_db": 11.0, "peak_intensity_db": 16.0},
                    {"location": "Rear Left", "p95_intensity_db": 24.0, "peak_intensity_db": 30.0},
                ],
                findings=[primary],
                top_causes=[primary],
                analysis_metadata={
                    "raw_capture_available": True,
                    "raw_backed_sample_count": 24,
                    "raw_capture_mode": "raw_backed",
                },
            )
        )
    )

    data = build_report_document(prepared)

    assert data.location_hotspot_rows[0].location == "Rear Left"
    assert data.proof_location_hotspot_rows[0].location == "Front Left"
    assert data.appendix_b.dominant_corner == "Front-Left"
    assert data.appendix_b.runner_up_corner == "Rear-Left"
    assert "raw-backed replay" in (data.appendix_b.proof_basis_note or "").lower()


def test_build_report_document_uses_domain_action_render_queries_for_next_steps() -> None:
    summary = minimal_summary(
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "engine",
                "confidence": 0.74,
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "engine",
                "confidence": 0.74,
            }
        ],
        test_plan=[
            {
                "action_id": "engine_mounts_and_accessories",
                "what": "  ACTION_ENGINE_MOUNTS_WHAT  ",
                "why": "  ACTION_ENGINE_MOUNTS_WHY  ",
                "confirm": "  ACTION_ENGINE_MOUNTS_CONFIRM  ",
                "falsify": "   ",
                "eta": " 15-30 min ",
            }
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.next_steps[0].action
    assert "engine mount" in data.next_steps[0].action.lower()
    assert data.next_steps[0].why
    assert data.next_steps[0].confirm
    assert data.next_steps[0].falsify is None
    assert data.next_steps[0].eta is None


def test_build_report_document_next_steps_do_not_leak_placeholder_tokens() -> None:
    summary = minimal_summary(
        findings=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        top_causes=[
            {
                "finding_id": "F001",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
                "strongest_location": "front-left wheel",
            }
        ],
        test_plan=[
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": "ACTION_WHEEL_BALANCE_WHY",
                "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
                "falsify": "ACTION_WHEEL_BALANCE_FALSIFY",
                "eta": "20-45 min",
            },
            {
                "action_id": "wheel_tire_condition",
                "what": "ACTION_TIRE_CONDITION_WHAT",
                "why": "ACTION_TIRE_CONDITION_WHY",
                "confirm": "ACTION_TIRE_CONDITION_CONFIRM",
                "falsify": "ACTION_TIRE_CONDITION_FALSIFY",
                "eta": "10-20 min",
            },
            {
                "action_id": "driveline_inspection",
                "what": "ACTION_DRIVELINE_INSPECTION_WHAT",
                "why": "ACTION_DRIVELINE_INSPECTION_WHY",
                "confirm": "ACTION_DRIVELINE_INSPECTION_CONFIRM",
                "falsify": "ACTION_DRIVELINE_INSPECTION_FALSIFY",
                "eta": "20-35 min",
            },
        ],
    )

    data = build_report_document(prepare_report_input(summary))
    assert len(data.next_steps) == 2
    assert all(step.eta is None for step in data.next_steps)
    assert all("front-left wheel" in step.action.lower() for step in data.next_steps)
    rendered = " ".join(
        part
        for step in data.next_steps
        for part in (step.action, step.why, step.confirm, step.falsify)
        if part
    )

    assert "{wheel_focus}" not in rendered
    assert "{speed_hint}" not in rendered
    assert "{location_hint}" not in rendered
    assert "{driveline_focus}" not in rendered
    assert "{" not in rendered
    assert "}" not in rendered


@pytest.mark.parametrize(
    ("primary_source", "expected_text", "unexpected_text"),
    [
        pytest.param(
            "engine",
            "check engine mounts and accessory drive",
            "tire damage",
            id="engine-trunk-hotspot",
        ),
        pytest.param(
            "driveline",
            "inspect propshaft runout/balance",
            "check driveline components near trunk",
            id="driveline-trunk-hotspot",
        ),
    ],
)
def test_build_report_document_keeps_generated_next_steps_on_primary_source_path_for_trunk_hotspots(
    primary_source: str,
    expected_text: str,
    unexpected_text: str,
) -> None:
    data = build_report_document(
        prepare_report_input(trunk_primary_guidance_summary(primary_source=primary_source))
    )

    rendered = " ".join(
        part
        for step in data.next_steps
        for part in (step.action, step.why, step.confirm, step.falsify)
        if part
    ).lower()

    assert expected_text in rendered
    assert unexpected_text not in rendered
    assert "check trunk for tire damage" not in rendered
    assert "imbalance or radial/lateral runout" not in rendered


def test_build_report_document_rephrases_ambiguous_primary_locations_as_mixed_signal() -> None:
    data = build_report_document(prepare_report_input(ambiguous_primary_location_summary()))

    expected = "Mixed signal between Front-Left and Rear-Left"

    assert data.verdict_page.inspect_first == expected
    assert data.verdict_page.dominant_corner == expected
    assert data.observed.strongest_location == expected


@pytest.mark.parametrize(
    ("mode", "expected_issue", "expected_step", "expected_condition"),
    [
        pytest.param(
            "steady",
            "Speed range never settled into a usable diagnostic band",
            "Repeat the same speed band with a longer steady hold",
            "Hold a repeatable steady-speed window",
            id="steady-speed-recature-guidance",
        ),
        pytest.param(
            "overlap",
            "Wheel / Tire and Driveline evidence overlapped",
            "Repeat the same speed band with separate drive/coast or load-change passes",
            "Cover the same speed band in separate drive/coast or load-change passes",
            id="source-overlap-recature-guidance",
        ),
        pytest.param(
            "weak",
            "Location evidence stayed spread across multiple positions",
            "Add sensor locations",
            "Keep all 4 expected positions connected throughout the run",
            id="weak-location-recature-guidance",
        ),
        pytest.param(
            "transient",
            "The strongest signal was transient or intermittent",
            "Repeat the same trigger several times",
            "Repeat the same trigger with enough before/after baseline",
            id="transient-recature-guidance",
        ),
    ],
)
def test_build_report_document_builds_scenario_specific_recapture_guidance(
    mode: str,
    expected_issue: str,
    expected_step: str,
    expected_condition: str,
) -> None:
    data = build_report_document(prepare_report_input(recapture_guidance_summary(mode)))

    assert data.appendix_a.mode == "recapture"
    assert any(expected_issue in line for line in data.appendix_a.capture_issues)
    assert any(expected_step in step.action for step in data.next_steps)
    assert any(expected_condition in line for line in data.appendix_a.capture_conditions)


def test_build_report_document_formats_report_timestamps_for_header() -> None:
    summary = minimal_summary(
        report_date="2026-03-25T10:00:00Z",
        start_time_utc="2026-03-25T09:55:00.536855+00:00",
        end_time_utc="2026-03-25T10:00:11.901770+00:00",
        metadata={"recorded_utc_offset_seconds": 7200},
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.run_datetime == "2026-03-25 12:00:00 UTC+02:00"
    assert data.start_time_utc == "2026-03-25 09:55:00 UTC"
    assert data.end_time_utc == "2026-03-25 10:00:11 UTC"


def test_build_report_document_backfills_peak_system_from_matching_finding() -> None:
    summary = minimal_summary(
        findings=[
            make_finding_payload(
                finding_id="F_PEAK",
                suspected_source="wheel/tire",
                confidence=0.82,
                strongest_location="front-left wheel",
                frequency_hz=41.0,
                frequency_hz_or_order="41.0 Hz",
            )
        ],
        top_causes=[
            make_finding_payload(
                finding_id="F_PEAK",
                suspected_source="wheel/tire",
                confidence=0.82,
                strongest_location="front-left wheel",
                frequency_hz=41.0,
                frequency_hz_or_order="41.0 Hz",
            )
        ],
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 41.0,
                    "order_label": "",
                    "suspected_source": "",
                    "p95_intensity_db": 18.0,
                    "strength_db": 18.0,
                    "presence_ratio": 0.8,
                    "peak_classification": "persistent",
                    "typical_speed_band": "50-80 km/h",
                }
            ]
        },
    )

    data = build_report_document(prepare_report_input(summary))

    assert len(data.peak_rows) == 1
    assert data.peak_rows[0].system == "Wheel / Tire"


def test_build_report_document_uses_connected_sensors_for_report_evidence() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=["Front Left", "Rear Left"],
        sensor_intensity_by_location=[
            {"location": "Front Left", "p95_intensity_db": 10.0},
            {"location": "Rear Left", "p95_intensity_db": 9.0},
            {"location": "Front Right", "p95_intensity_db": 18.0},
        ],
    )

    data = build_report_document(prepare_report_input(summary))
    assert data.sensor_count == 2
    assert data.sensor_locations == ["Front Left", "Rear Left"]
    assert [row.location for row in data.sensor_intensity_by_location] == [
        "Front Left",
        "Rear Left",
    ]


def test_most_likely_origin_summary_weak_spatial_disambiguates_location() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Rear Left",
                "location_hotspot": {
                    "top_location": "Rear Left",
                    "ambiguous_locations": ["Rear Left", "Front Right"],
                    "ambiguous_location": True,
                },
                "suspected_source": "wheel/tire",
                "dominance_ratio": 1.05,
                "weak_spatial_separation": True,
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.81,
            },
            {
                "strongest_location": "Front Right",
                "suspected_source": "wheel/tire",
                "confidence": 0.74,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None
    assert origin.summary_location == "Rear Left / Front Right"
    assert origin.alternative_locations == ("Front Right",)


@pytest.mark.parametrize(
    ("phase", "location", "speed_band", "confidence"),
    [
        ("acceleration", "Front Right", "60-80 km/h", 0.75),
        ("deceleration", "Rear Left", "40-60 km/h", 0.70),
    ],
    ids=["acceleration_en", "deceleration_nl"],
)
def test_most_likely_origin_summary_phase_onset(
    phase: str,
    location: str,
    speed_band: str,
    confidence: float,
) -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": location,
                "suspected_source": "wheel/tire",
                "dominance_ratio": 2.5,
                "weak_spatial_separation": False,
                "strongest_speed_band": speed_band,
                "dominant_phase": phase,
                "confidence": confidence,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None

    assert origin.dominant_phase == phase
    explanation = _origin_explanation(origin)
    assert isinstance(explanation, list)
    assert any(
        isinstance(part, dict)
        and part.get("_i18n_key") == "ORIGIN_PHASE_ONSET_NOTE"
        and part.get("phase") == phase
        for part in explanation
    )


def test_most_likely_origin_summary_no_phase_onset_for_cruise() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Front Left",
                "suspected_source": "wheel/tire",
                "dominance_ratio": 3.0,
                "weak_spatial_separation": False,
                "strongest_speed_band": "80-100 km/h",
                "dominant_phase": "cruise",
                "confidence": 0.80,
            },
        ]
    )

    origin = summarize_origin(findings)
    assert origin is not None
    _assert_no_phase_onset(_origin_explanation(origin))


def test_most_likely_origin_summary_no_phase_onset_when_absent() -> None:
    findings = tuple(
        finding_from_payload(p)
        for p in [
            {
                "strongest_location": "Front Left",
                "suspected_source": "wheel/tire",
                "dominance_ratio": 3.0,
                "weak_spatial_separation": False,
                "strongest_speed_band": "80-100 km/h",
                "confidence": 0.80,
            },
        ]
    )

    origin = summarize_origin(findings)

    assert origin is not None
    assert origin.dominant_phase is None
    _assert_no_phase_onset(_origin_explanation(origin))

    summary = minimal_summary(
        lang="en",
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Rear Left",
                "strongest_speed_band": "80-90 km/h",
                "confidence": 0.83,
                "weak_spatial_separation": True,
                "signatures_observed": ["1x wheel order"],
                "confidence_tone": "warn",
            },
        ],
        most_likely_origin={
            "location": "Rear Left / Front Right",
            "alternative_locations": ["Front Right"],
            "explanation": "Weak spatial separation.",
        },
    )

    data = build_report_document(prepare_report_input(summary))
    assert data.observed.strongest_location == "Mixed signal between Rear-Left and Front-Right"


def test_build_report_document_peak_rows_use_persistence_metrics() -> None:
    summary = minimal_summary(
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 33.0,
                    "order_label": "",
                    "max_intensity_db": 22.0,
                    "p95_intensity_db": 18.4,
                    "strength_db": 18.4,
                    "presence_ratio": 0.85,
                    "persistence_score": 0.0867,
                    "peak_classification": "patterned",
                    "typical_speed_band": "60-80 km/h",
                },
            ],
        },
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.peak_rows
    row = data.peak_rows[0]
    assert row.peak_db == "18.4"
    assert row.strength_db == "18.4"
    assert row.relevance == "Repeated pattern"
    assert "%" not in row.relevance


def test_build_report_document_peak_rows_render_baseline_noise_label() -> None:
    summary = minimal_summary(
        lang="en",
        plots={
            "peaks_table": [
                {
                    "rank": 1,
                    "frequency_hz": 18.0,
                    "order_label": "",
                    "max_intensity_db": 2.1,
                    "p95_intensity_db": 2.1,
                    "strength_db": 2.1,
                    "presence_ratio": 0.1,
                    "persistence_score": 0.001,
                    "peak_classification": "baseline_noise",
                    "typical_speed_band": "any",
                },
            ],
        },
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.peak_rows
    assert data.peak_rows[0].relevance == "Near noise floor"


def test_build_report_document_data_trust_keeps_warning_detail() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": {
                    "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_WARN",
                    "total_dropped": 3,
                    "total_overflow": 2,
                },
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.data_trust
    assert data.data_trust[0].state == "warn"
    assert data.data_trust[0].check == "Frame-integriteit"
    assert data.data_trust[0].detail == "3 verloren frames, 2 wachtrijoverlopen gedetecteerd."


def test_build_report_document_data_trust_literal_check_labels() -> None:
    summary = minimal_summary(
        lang="nl",
        run_suitability=[
            {
                "check_key": "Frame integrity",
                "state": "warn",
                "explanation": "3 dropped frames, 2 queue overflows detected.",
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.data_trust
    assert data.data_trust[0].check == "Frame integrity"


def test_build_report_document_data_trust_includes_run_context_warnings() -> None:
    summary = minimal_summary(
        lang="en",
        warnings=[
            {
                "code": "reference_context_incomplete",
                "severity": "warn",
                "applies_to": "order_analysis",
                "title": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"},
                "detail": {"_i18n_key": "RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"},
            },
        ],
    )
    data = build_report_document(prepare_report_input(summary))
    assert any(
        item.check == "Order-analysis reference context was incomplete for this run"
        for item in data.data_trust
    )


def test_build_report_document_data_trust_check_labels_follow_lang_for_same_summary_data() -> None:
    base_summary = minimal_summary(
        run_suitability=[
            {
                "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
                "state": "pass",
                "explanation": (
                    "Speed range stayed in a usable diagnostic band for steady-state diagnosis "
                    "and order tracking."
                ),
            },
        ],
    )

    summary_en = {**base_summary, "lang": "en"}
    summary_nl = {**base_summary, "lang": "nl"}

    data_en = build_report_document(prepare_report_input(summary_en))
    data_nl = build_report_document(prepare_report_input(summary_nl))

    assert data_en.data_trust[0].check == "Speed variation"
    assert data_nl.data_trust[0].check == "Snelheidsvariatie"


def test_build_report_document_certainty_reason_ignores_unrelated_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        top_causes=[
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Front Left",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = build_report_document(prepare_report_input(summary))
    assert data.observed.certainty_reason
    assert "Missing reference data" not in data.observed.certainty_reason


def test_build_report_document_certainty_reason_keeps_relevant_reference_gap() -> None:
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations={"FL": {}, "FR": {}, "RL": {}, "RR": {}},
        speed_stats={"steady_speed": True},
        run_suitability=[
            {"check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS", "state": "warn"},
        ],
        top_causes=[
            {
                "finding_id": "F_ENGINE",
                "suspected_source": "engine",
                "strongest_location": "Engine Bay",
                "strongest_speed_band": "60-80 km/h",
                "confidence": 0.82,
            },
        ],
        findings=[{"finding_id": "REF_ENGINE"}],
    )
    data = build_report_document(prepare_report_input(summary))
    assert "Missing reference data" in data.observed.certainty_reason


def test_build_report_document_builds_verdict_timeline_graph_from_phase_timeline() -> None:
    finding = make_finding_payload(
        finding_id="F_TIMELINE",
        suspected_source="wheel/tire",
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        confidence=0.82,
    )
    summary = minimal_summary(
        lang="en",
        duration_s=12.0,
        findings=[finding],
        top_causes=[finding],
        phase_timeline=[
            {
                "phase": "cruise",
                "start_t_s": 0.0,
                "end_t_s": 4.0,
                "speed_min_kmh": 58.0,
                "speed_max_kmh": 63.0,
                "has_fault_evidence": False,
            },
            {
                "phase": "cruise",
                "start_t_s": 4.0,
                "end_t_s": 9.0,
                "speed_min_kmh": 64.0,
                "speed_max_kmh": 72.0,
                "has_fault_evidence": True,
            },
            {
                "phase": "decel",
                "start_t_s": 9.0,
                "end_t_s": 12.0,
                "speed_min_kmh": 48.0,
                "speed_max_kmh": 62.0,
                "has_fault_evidence": False,
            },
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    timeline = data.verdict_page.timeline_graph
    assert timeline is not None
    assert timeline.duration_s == 12.0
    assert timeline.speed_ceiling_kmh >= 72.0
    assert [(interval.start_t_s, interval.end_t_s) for interval in timeline.intervals] == [
        (0.0, 4.0),
        (4.0, 9.0),
        (9.0, 12.0),
    ]
    assert [interval.has_fault_evidence for interval in timeline.intervals] == [False, True, False]


def test_build_report_document_softens_same_corner_wheel_driveline_overlap_wording() -> None:
    overlap_reason = (
        "Wheel and driveline evidence overlap, so the system could not strongly "
        "differentiate between them; inspect both areas."
    )
    wheel = make_finding_payload(
        finding_id="F_WHEEL",
        suspected_source="wheel/tire",
        confidence=0.66,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.4,
                "location": "Front Left",
            },
            {
                "speed_kmh": 68.0,
                "predicted_hz": 14.0,
                "matched_hz": 14.1,
                "location": "Front Left",
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="66%",
        confidence_reason=overlap_reason,
    )
    driveline = make_finding_payload(
        finding_id="F_DRIVELINE",
        suspected_source="driveline",
        confidence=0.61,
        strongest_location="Front Left",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x driveshaft",
        signatures_observed=["1x driveshaft"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 26.4,
                "matched_hz": 26.8,
                "location": "Front Left",
            },
            {
                "speed_kmh": 68.0,
                "predicted_hz": 28.0,
                "matched_hz": 28.2,
                "location": "Front Left",
            },
        ],
        confidence_label_key="CONFIDENCE_MEDIUM",
        confidence_tone="warn",
        confidence_pct="61%",
        confidence_reason=overlap_reason,
    )
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        speed_stats={"steady_speed": True},
        findings=[wheel, driveline],
        top_causes=[wheel, driveline],
        test_plan=[
            {
                "action_id": "wheel_balance_and_runout",
                "what": "ACTION_WHEEL_BALANCE_WHAT",
                "why": "ACTION_WHEEL_BALANCE_WHY",
                "confirm": "ACTION_WHEEL_BALANCE_CONFIRM",
            }
        ],
    )

    data = build_report_document(prepare_report_input(summary))

    assert data.verdict_page.also_consider is not None
    assert "Driveline" in data.verdict_page.also_consider
    assert data.appendix_a.why_alternative_next is not None
    alternative_reason = data.appendix_a.why_alternative_next.lower()
    assert "wheel and driveline evidence overlap" in alternative_reason
    assert "stayed strongest near front-left" not in alternative_reason
    assert data.appendix_c.evidence_summary is not None
    evidence_summary = data.appendix_c.evidence_summary.lower()
    assert "wheel and driveline evidence overlap" in evidence_summary
    assert "1x driveshaft also stayed strongest near front-left" not in evidence_summary


def test_build_report_document_surfaces_temporal_shift_in_page_one_and_appendix() -> None:
    data = build_report_document(prepare_report_input(sequential_same_source_summary()))

    assert data.verdict_page.suspected_source == "Wheel / Tire"
    assert data.verdict_page.inspect_first == "Front-Left"
    assert data.verdict_page.proof_summary is not None
    proof_summary = data.verdict_page.proof_summary
    assert "Front-Left" in proof_summary
    assert "Rear-Right" in proof_summary
    assert "remained the strongest connected location" not in proof_summary

    assert data.appendix_c.phase_summary is not None
    phase_summary = data.appendix_c.phase_summary
    assert "Front-Left" in phase_summary
    assert "Rear-Right" in phase_summary
    assert "acceleration" in phase_summary
    assert "deceleration" in phase_summary

    assert data.appendix_c.evidence_summary is not None
    evidence_summary = data.appendix_c.evidence_summary
    assert "Front-Left" in evidence_summary
    assert "Rear-Right" in evidence_summary
    assert "stayed strongest at Front-Left" not in evidence_summary


def test_build_report_document_builds_sensor_observation_matrix_rows() -> None:
    wheel = make_finding_payload(
        finding_id="F_SENSOR_MATRIX",
        suspected_source="wheel/tire",
        confidence=0.82,
        strongest_location="Front Left wheel",
        strongest_speed_band="60-80 km/h",
        frequency_hz_or_order="1x wheel order",
        signatures_observed=["1x wheel order"],
        matched_points=[
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.3,
                "location": "Front Left wheel",
                "amp": 0.10,
            },
            {
                "speed_kmh": 67.0,
                "predicted_hz": 14.2,
                "matched_hz": 14.3,
                "location": "Front Left wheel",
                "amp": 0.08,
            },
            {
                "speed_kmh": 62.0,
                "predicted_hz": 13.2,
                "matched_hz": 13.4,
                "location": "Front Right wheel",
                "amp": 0.05,
            },
            {
                "speed_kmh": 67.0,
                "predicted_hz": 14.2,
                "matched_hz": 14.4,
                "location": "Rear Left wheel",
                "amp": 0.025,
            },
        ],
    )
    summary = minimal_summary(
        lang="en",
        sensor_count_used=4,
        sensor_locations=["Front Left", "Front Right", "Rear Left", "Rear Right"],
        sensor_locations_connected_throughout=[
            "Front Left",
            "Front Right",
            "Rear Left",
            "Rear Right",
        ],
        findings=[wheel],
        top_causes=[wheel],
    )

    data = build_report_document(prepare_report_input(summary))

    assert len(data.appendix_b.sensor_observation_rows) == 1
    row = data.appendix_b.sensor_observation_rows[0]
    assert row.source_name == "Wheel / Tire"
    assert row.signal_label == "1x wheel order"
    assert [cell.location for cell in row.sensor_levels] == [
        "Front-Left",
        "Front-Right",
        "Rear-Left",
        "Rear-Right",
    ]
    assert row.sensor_levels[0].relative_level_db == pytest.approx(0.0)
    assert row.sensor_levels[1].relative_level_db == pytest.approx(-5.6, abs=0.5)
    assert row.sensor_levels[2].relative_level_db is not None
    assert row.sensor_levels[2].relative_level_db < row.sensor_levels[1].relative_level_db
    assert row.sensor_levels[3].relative_level_db is None
