"""Focused Finding and Report contract tests."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from vibesensor.domain import Finding
from vibesensor.shared.boundaries.reporting.document import Report, ReportDocument


@pytest.mark.parametrize(
    ("confidence", "expected_pct"),
    [
        (None, None),
        (0.0, 0),
        (0.0049, 0),
        (0.005, 0),
        (0.0051, 1),
        (0.245, 24),
        (0.255, 26),
        (0.9949, 99),
        (0.995, 100),
        (1.0, 100),
    ],
)
def test_finding_confidence_pct_covers_rounding_boundaries(
    confidence: float | None,
    expected_pct: int | None,
) -> None:
    finding = Finding(confidence=confidence)

    assert finding.confidence_pct == expected_pct


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_rejects_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="must be in \\[0, 1\\]"):
        Finding(confidence=confidence)


def test_report_serializes_core_metadata_for_document_consumers() -> None:
    report = Report(
        run_id="run-123",
        title="Diagnostic Report",
        lang="nl",
        car_name="BMW 3 Series",
        car_type="sedan",
        duration_s=18.5,
        sample_count=3200,
        sensor_count=4,
    )

    payload = asdict(report)
    serialized = json.loads(json.dumps(payload))
    document = ReportDocument(
        title=report.title,
        run_id=report.run_id,
        car_name=report.car_name,
        car_type=report.car_type,
        sample_count=report.sample_count,
        sensor_count=report.sensor_count,
        lang=report.lang,
    )

    assert serialized == {
        "run_id": "run-123",
        "title": "Diagnostic Report",
        "lang": "nl",
        "car_name": "BMW 3 Series",
        "car_type": "sedan",
        "report_date": None,
        "duration_s": 18.5,
        "sample_count": 3200,
        "sensor_count": 4,
    }
    assert document.run_id == report.run_id
    assert document.car_name == report.car_name
    assert document.car_type == report.car_type
    assert document.sample_count == report.sample_count
    assert document.sensor_count == report.sensor_count
    assert document.lang == report.lang


def test_report_rejects_empty_run_id() -> None:
    with pytest.raises(ValueError, match="run_id must be non-empty"):
        Report(run_id="")


def test_report_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_s must be non-negative"):
        Report(run_id="r1", duration_s=-1.0)


def test_report_allows_zero_duration() -> None:
    report = Report(run_id="r1", duration_s=0.0)
    assert report.duration_s == 0.0
