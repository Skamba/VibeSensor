"""Tests for the report-payload projection gate helper."""

from __future__ import annotations

from vibesensor.shared.boundaries.report_payload_gate import has_projectable_report_payload


def test_has_projectable_report_payload_accepts_findings_list() -> None:
    assert has_projectable_report_payload({"findings": []}) is True


def test_has_projectable_report_payload_accepts_top_causes_list() -> None:
    assert has_projectable_report_payload({"top_causes": []}) is True


def test_has_projectable_report_payload_rejects_missing_projection_lists() -> None:
    assert has_projectable_report_payload({"run_id": "no-projection"}) is False


def test_has_projectable_report_payload_rejects_non_list_projection_values() -> None:
    assert has_projectable_report_payload({"findings": {}, "top_causes": None}) is False
