from __future__ import annotations

import pytest
from test_support.whole_run_diagnosis_scenarios import whole_run_diagnosis_scenarios


@pytest.mark.parametrize("scenario", whole_run_diagnosis_scenarios(), ids=lambda case: case.case_id)
def test_whole_run_diagnosis_scenarios_cover_ranker_outcomes(scenario) -> None:
    summaries = scenario.build_diagnosis_summaries()

    assert [summary.suspected_source for summary in summaries] == list(
        scenario.expected_ranked_sources
    )
    assert summaries[0].ambiguous_diagnosis is scenario.expected_primary_ambiguous
    assert summaries[0].suspicious is scenario.expected_primary_suspicious
    assert {factor.factor_key for factor in summaries[0].counterevidence_factors} >= set(
        scenario.expected_primary_counterevidence_keys
    )
    if len(summaries) > 1 and scenario.expected_runner_up_counterevidence_keys:
        assert {factor.factor_key for factor in summaries[1].counterevidence_factors} >= set(
            scenario.expected_runner_up_counterevidence_keys
        )
