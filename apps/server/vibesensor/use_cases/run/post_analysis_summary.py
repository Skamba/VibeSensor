"""Persisted-analysis summary building for completed recording runs."""

from __future__ import annotations

from typing import cast

from vibesensor.shared.boundaries.analysis_payload import RunSuitabilityCheck
from vibesensor.shared.boundaries.analysis_summary import (
    AnalysisResultLike,
    analysis_result_to_summary,
)
from vibesensor.shared.boundaries.persisted_analysis_codec import (
    persisted_analysis_from_summary,
)
from vibesensor.shared.types.backend_types import RunMetadata
from vibesensor.shared.types.history_analysis_contracts import PayloadObject
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import PersistedAnalysis
from vibesensor.shared.types.sensor_frame import SensorFrame


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
    from vibesensor.use_cases.diagnostics import RunAnalysis

    result = RunAnalysis(
        metadata.to_dict(),
        samples,
        lang=language,
        file_name=run_id,
        include_samples=False,
    ).summarize()
    summary_payload = analysis_result_to_summary(cast(AnalysisResultLike, result))
    summary_payload["case_id"] = result.diagnostic_case.case_id

    analysis_metadata: JsonObject = {
        "analyzed_sample_count": len(samples),
        "total_sample_count": total_sample_count,
        "sampling_method": "full" if stride == 1 else f"stride_{stride}",
    }
    summary_payload["analysis_metadata"] = cast(PayloadObject, analysis_metadata)

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
        run_suitability = summary_payload.get("run_suitability")
        if not isinstance(run_suitability, list):
            run_suitability = []
            summary_payload["run_suitability"] = run_suitability
        warning_payload: RunSuitabilityCheck = {
            "check_key": stride_check.check_key,
            "check": stride_check.check_key,
            "state": stride_check.state,
            "explanation": explanation,
        }
        run_suitability.append(warning_payload)

    return persisted_analysis_from_summary(summary_payload)
