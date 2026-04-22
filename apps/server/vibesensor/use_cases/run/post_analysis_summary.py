"""Persisted-analysis summary building for completed recording runs."""

from __future__ import annotations

from vibesensor.shared.boundaries.analysis_payloads import analysis_result_to_summary
from vibesensor.shared.json_utils import payload_object_from_json
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.use_cases.run.post_analysis_input import PostAnalysisRunInput

_MIN_POST_ANALYSIS_DURATION_S = 1.0


def build_post_analysis_summary(run: PostAnalysisRunInput) -> PersistedAnalysis:
    """Run diagnostics analysis and return the internal persisted-analysis object."""
    from vibesensor.domain import SuitabilityCheck
    from vibesensor.report_i18n import tr
    from vibesensor.use_cases.diagnostics.run_analysis import RunAnalysis

    result = RunAnalysis(
        run.diagnostics_run,
        lang=run.language,
        file_name=run.run_id,
        include_samples=False,
    ).summarize()
    summary_payload = analysis_result_to_summary(result)
    summary_payload["case_id"] = result.diagnostic_case.case_id

    def append_run_suitability_warning(
        *,
        check_key: str,
        state: str,
        explanation: str,
    ) -> None:
        run_suitability = summary_payload.get("run_suitability")
        if run_suitability is None:
            run_suitability = []
            summary_payload["run_suitability"] = run_suitability
        warning_payload: RunSuitabilityCheck = {
            "check_key": check_key,
            "state": state,
            "explanation": explanation,
        }
        run_suitability.append(warning_payload)

    analysis_metadata: JsonObject = {
        "analyzed_sample_count": len(run.samples),
        "total_sample_count": run.total_sample_count,
        "sampling_method": "full" if run.stride == 1 else f"stride_{run.stride}",
        "raw_capture_available": run.raw_capture_available,
        "raw_backed_sample_count": run.raw_backed_sample_count,
        "raw_capture_mode": "raw_backed" if run.raw_backed_sample_count > 0 else "summary_only",
    }
    summary_payload["analysis_metadata"] = payload_object_from_json(analysis_metadata)

    sample_rate_hz = _post_analysis_sample_rate_hz(run)
    if sample_rate_hz is not None and run.total_sample_count < max(
        1,
        int(sample_rate_hz * _MIN_POST_ANALYSIS_DURATION_S),
    ):
        short_run_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_RUN_DURATION",
            state="warn",
        )
        explanation = tr(run.language, "SUITABILITY_RUN_DURATION_WARNING")
        append_run_suitability_warning(
            check_key=short_run_check.check_key,
            state=short_run_check.state,
            explanation=explanation,
        )

    if run.stride > 1:
        stride_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
            details=(("stride", run.stride),),
        )
        explanation = tr(
            run.language,
            "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
            stride=str(run.stride),
        )
        append_run_suitability_warning(
            check_key=stride_check.check_key,
            state=stride_check.state,
            explanation=explanation,
        )

    return PersistedAnalysis.from_json_object(summary_payload)


def _post_analysis_sample_rate_hz(run: PostAnalysisRunInput) -> int | None:
    """Resolve the sample rate from the canonical diagnostics context only."""
    raw_sample_rate_hz = run.context.raw_sample_rate_hz
    if raw_sample_rate_hz is not None and raw_sample_rate_hz > 0:
        return int(raw_sample_rate_hz)
    return None
