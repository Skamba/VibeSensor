"""Persisted-analysis summary building for completed recording runs."""

from __future__ import annotations

from vibesensor.shared.boundaries.analysis_summary import analysis_result_to_summary
from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_summary,
)
from vibesensor.shared.json_utils import payload_object_from_json
from vibesensor.shared.types.history_analysis_contracts import RunSuitabilityCheck
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame

_MIN_POST_ANALYSIS_DURATION_S = 1.0


def build_post_analysis_summary(
    *,
    run_id: str,
    metadata: RunMetadata,
    samples: list[SensorFrame],
    language: str,
    total_sample_count: int,
    stride: int,
) -> PersistedAnalysis:
    """Run diagnostics analysis and return the internal persisted-analysis object."""
    from vibesensor.domain import SuitabilityCheck
    from vibesensor.report_i18n import tr
    from vibesensor.use_cases.diagnostics.summary_builder import RunAnalysis

    result = RunAnalysis(
        metadata.to_dict(),
        samples,
        lang=language,
        file_name=run_id,
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
        "analyzed_sample_count": len(samples),
        "total_sample_count": total_sample_count,
        "sampling_method": "full" if stride == 1 else f"stride_{stride}",
    }
    summary_payload["analysis_metadata"] = payload_object_from_json(analysis_metadata)

    sample_rate_hz = _post_analysis_sample_rate_hz(metadata)
    if sample_rate_hz is not None and total_sample_count < max(
        1, int(sample_rate_hz * _MIN_POST_ANALYSIS_DURATION_S)
    ):
        short_run_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_RUN_DURATION",
            state="warn",
        )
        explanation = tr(language, "SUITABILITY_RUN_DURATION_WARNING")
        append_run_suitability_warning(
            check_key=short_run_check.check_key,
            state=short_run_check.state,
            explanation=explanation,
        )

    if stride > 1:
        stride_check = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
            details=(("stride", stride),),
        )
        explanation = tr(
            language,
            "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
            stride=str(stride),
        )
        append_run_suitability_warning(
            check_key=stride_check.check_key,
            state=stride_check.state,
            explanation=explanation,
        )

    return persisted_analysis_from_summary(summary_payload)


def _post_analysis_sample_rate_hz(metadata: RunMetadata) -> int | None:
    """Resolve the sample rate used for duration checks from canonical or extra metadata."""
    raw_sample_rate_hz = metadata.raw_sample_rate_hz
    if raw_sample_rate_hz is not None and raw_sample_rate_hz > 0:
        return raw_sample_rate_hz
    extra_sample_rate_hz = metadata.extras.get("sample_rate_hz")
    if isinstance(extra_sample_rate_hz, int) and extra_sample_rate_hz > 0:
        return extra_sample_rate_hz
    if isinstance(extra_sample_rate_hz, float) and extra_sample_rate_hz > 0:
        return int(extra_sample_rate_hz)
    return None
