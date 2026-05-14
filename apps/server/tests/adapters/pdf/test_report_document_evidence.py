"""Focused report document projection contracts."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding_payload
from test_support.report_helpers import (
    minimal_summary,
)

from vibesensor import report_i18n
from vibesensor.shared.boundaries.reporting import (
    prepare_persisted_report_input,
    prepare_report_input,
)
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.history.report_document import build_report_document


def _tr(key: str, **kwargs: object) -> str:
    return report_i18n.tr("en", key, **kwargs)


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
        _tr("CONFIDENCE_LABEL"),
        _tr("REPORT_EVIDENCE_BASIS_LABEL"),
        _tr("REPORT_SUPPORT_WINDOW_SUMMARY_LABEL"),
        _tr("REPORT_STABLE_FREQUENCY_LABEL"),
    ]
    assert data.verdict_page.proof_snapshot_rows[0].value.startswith(
        f"{_tr('CONFIDENCE_MEDIUM')} ("
    )
    assert data.verdict_page.proof_snapshot_rows[1].value == _tr(
        "REPORT_EVIDENCE_BASIS_RAW",
        samples="24",
    )
    assert data.verdict_page.proof_snapshot_rows[2].value == _tr(
        "REPORT_SUPPORT_WINDOW_SUMMARY_COUNT_ONLY",
        count="3",
    )
    assert data.verdict_page.proof_snapshot_rows[3].value == _tr(
        "REPORT_STABLE_FREQUENCY_BAND",
        low="15.1",
        high="15.4",
    )
    assert [row.label for row in data.appendix_c.evidence_snapshot_rows] == [
        _tr("CONFIDENCE_LABEL"),
        _tr("REPORT_EVIDENCE_BASIS_LABEL"),
        _tr("REPORT_SUPPORT_WINDOW_SUMMARY_LABEL"),
        _tr("REPORT_STABLE_FREQUENCY_LABEL"),
        _tr("REPORT_SUPPORTING_SENSORS_LABEL"),
        _tr("REPORT_COUNTEREVIDENCE_LABEL"),
    ]
    assert data.appendix_c.evidence_snapshot_rows[4].value == ", ".join(
        [
            _tr("REPORT_SUPPORTING_SENSOR_ENTRY", location="Front-Left", count="2"),
            _tr("REPORT_SUPPORTING_SENSOR_ENTRY", location="Rear-Left", count="1"),
        ]
    )
    assert data.appendix_c.evidence_snapshot_rows[5].value == "; ".join(
        [
            _tr("REPORT_COUNTEREVIDENCE_ALT_SOURCE", source="Driveline"),
            _tr("REPORT_COUNTEREVIDENCE_WEAK_SPATIAL"),
        ]
    )


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
    assert prepared.report_facts.evidence.data_basis == "raw_backed"
    assert prepared.report_facts.evidence.raw_backed_sample_count == 24


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
