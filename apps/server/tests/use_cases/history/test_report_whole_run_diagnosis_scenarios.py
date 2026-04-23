from __future__ import annotations

import pytest
from test_support.whole_run_diagnosis_scenarios import whole_run_diagnosis_scenarios

from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.history.report_document import build_report_document


@pytest.mark.parametrize("scenario", whole_run_diagnosis_scenarios(), ids=lambda case: case.case_id)
def test_report_document_whole_run_diagnosis_scenarios(scenario) -> None:
    document = build_report_document(prepare_report_input(scenario.build_report_summary()))

    assert document.verdict_page.suspected_source == scenario.expected_report_source
    assert document.verdict_page.inspect_first == scenario.expected_report_location
    assert document.verdict_page.also_consider == scenario.expected_report_alternative
    assert any(
        scenario.expected_report_frequency_fragment in row.value
        for row in document.verdict_page.proof_snapshot_rows
        if row.label == "Stable frequency"
    )
