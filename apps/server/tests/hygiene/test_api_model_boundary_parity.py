from __future__ import annotations

from typing import Protocol

import pytest

from vibesensor.adapters.http.models.history import (
    AmplitudeMetric as ApiAmplitudeMetric,
)
from vibesensor.adapters.http.models.history import (
    AmpVsPhaseRow as ApiAmpVsPhaseRow,
)
from vibesensor.adapters.http.models.history import (
    DataQualityAccelSanityResponse as ApiDataQualityAccelSanityResponse,
)
from vibesensor.adapters.http.models.history import (
    DataQualityOutliersResponse as ApiDataQualityOutliersResponse,
)
from vibesensor.adapters.http.models.history import (
    DataQualityRequiredMissingPctResponse as ApiDataQualityRequiredMissingPctResponse,
)
from vibesensor.adapters.http.models.history import (
    DataQualityResponse as ApiDataQualityResponse,
)
from vibesensor.adapters.http.models.history import (
    DataQualitySpeedCoverageResponse as ApiDataQualitySpeedCoverageResponse,
)
from vibesensor.adapters.http.models.history import (
    FindingEvidenceMetrics as ApiFindingEvidenceMetrics,
)
from vibesensor.adapters.http.models.history import (
    FindingPayload as ApiFindingPayload,
)
from vibesensor.adapters.http.models.history import (
    FreqVsSpeedByFindingSeries as ApiFreqVsSpeedByFindingSeries,
)
from vibesensor.adapters.http.models.history import (
    LocationHotspotPayload as ApiLocationHotspotPayload,
)
from vibesensor.adapters.http.models.history import (
    LocationIntensitySummaryResponse as ApiLocationIntensitySummaryResponse,
)
from vibesensor.adapters.http.models.history import (
    MatchedAmpVsSpeedSeries as ApiMatchedAmpVsSpeedSeries,
)
from vibesensor.adapters.http.models.history import (
    MatchedPoint as ApiMatchedPoint,
)
from vibesensor.adapters.http.models.history import (
    OutlierSummaryResponse as ApiOutlierSummaryResponse,
)
from vibesensor.adapters.http.models.history import (
    PeakTableRow as ApiPeakTableRow,
)
from vibesensor.adapters.http.models.history import (
    PhaseBoundary as ApiPhaseBoundary,
)
from vibesensor.adapters.http.models.history import (
    PhaseEvidence as ApiPhaseEvidence,
)
from vibesensor.adapters.http.models.history import (
    PhaseInfoResponse as ApiPhaseInfoResponse,
)
from vibesensor.adapters.http.models.history import (
    PhaseIntensityStatsResponse as ApiPhaseIntensityStatsResponse,
)
from vibesensor.adapters.http.models.history import (
    PhaseSegmentOut as ApiPhaseSegmentOut,
)
from vibesensor.adapters.http.models.history import (
    PhaseSegmentSummaryResponse as ApiPhaseSegmentSummaryResponse,
)
from vibesensor.adapters.http.models.history import (
    PhaseSpeedBreakdownRow as ApiPhaseSpeedBreakdownRow,
)
from vibesensor.adapters.http.models.history import (
    PhaseTimelineEntryResponse as ApiPhaseTimelineEntryResponse,
)
from vibesensor.adapters.http.models.history import (
    PlotDataResult as ApiPlotDataResult,
)
from vibesensor.adapters.http.models.history import (
    RunSuitabilityCheck as ApiRunSuitabilityCheck,
)
from vibesensor.adapters.http.models.history import (
    SpectrogramResult as ApiSpectrogramResult,
)
from vibesensor.adapters.http.models.history import (
    SpeedBreakdownRow as ApiSpeedBreakdownRow,
)
from vibesensor.adapters.http.models.history import (
    SpeedStatsResponse as ApiSpeedStatsResponse,
)
from vibesensor.adapters.http.models.history import (
    StrengthBucketDistributionResponse as ApiStrengthBucketDistributionResponse,
)
from vibesensor.adapters.http.models.history import (
    SummaryWarningResponse as ApiSummaryWarningResponse,
)
from vibesensor.adapters.http.models.history import (
    SuspectedVibrationOriginPayload as ApiSuspectedVibrationOriginPayload,
)
from vibesensor.adapters.http.models.history import (
    TestPlanStepResponse as ApiTestPlanStepResponse,
)
from vibesensor.shared.boundaries.vibration_origin import (
    SuspectedVibrationOrigin as BoundarySuspectedVibrationOrigin,
)
from vibesensor.shared.types.analysis_views import (
    AmpVsPhaseRow as BoundaryAmpVsPhaseRow,
)
from vibesensor.shared.types.analysis_views import (
    FindingEvidenceMetrics as BoundaryFindingEvidenceMetrics,
)
from vibesensor.shared.types.analysis_views import (
    FreqVsSpeedByFindingSeries as BoundaryFreqVsSpeedByFindingSeries,
)
from vibesensor.shared.types.analysis_views import (
    LocationHotspotPayload as BoundaryLocationHotspotPayload,
)
from vibesensor.shared.types.analysis_views import (
    MatchedAmpVsSpeedSeries as BoundaryMatchedAmpVsSpeedSeries,
)
from vibesensor.shared.types.analysis_views import (
    MatchedPoint as BoundaryMatchedPoint,
)
from vibesensor.shared.types.analysis_views import (
    PeakTableRow as BoundaryPeakTableRow,
)
from vibesensor.shared.types.analysis_views import (
    PhaseBoundary as BoundaryPhaseBoundary,
)
from vibesensor.shared.types.analysis_views import (
    PhaseEvidence as BoundaryPhaseEvidence,
)
from vibesensor.shared.types.analysis_views import (
    PhaseSegmentOut as BoundaryPhaseSegmentOut,
)
from vibesensor.shared.types.analysis_views import (
    PhaseSpeedBreakdownRow as BoundaryPhaseSpeedBreakdownRow,
)
from vibesensor.shared.types.analysis_views import (
    PlotDataResult as BoundaryPlotDataResult,
)
from vibesensor.shared.types.analysis_views import (
    SpectrogramResult as BoundarySpectrogramResult,
)
from vibesensor.shared.types.analysis_views import (
    SpeedBreakdownRow as BoundarySpeedBreakdownRow,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AmplitudeMetric as BoundaryAmplitudeMetric,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummary as BoundaryAnalysisSummary,
)
from vibesensor.shared.types.history_analysis_contracts import (
    AnalysisSummaryResponse as ApiAnalysisSummaryResponse,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityAccelSanityResponse as BoundaryDataQualityAccelSanityPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityOutliersResponse as BoundaryDataQualityOutliersPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityRequiredMissingPctResponse as BoundaryDataQualityRequiredMissingPctPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualityResponse as BoundaryDataQualityPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    DataQualitySpeedCoverageResponse as BoundaryDataQualitySpeedCoveragePayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    FindingPayload as BoundaryFindingPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    LocationIntensitySummaryResponse as BoundaryLocationIntensitySummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    OutlierSummaryResponse as BoundaryOutlierSummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseInfoResponse as BoundaryPhaseInfoPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseIntensityStatsResponse as BoundaryPhaseIntensityStatsPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseSegmentSummaryResponse as BoundaryPhaseSegmentSummaryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseTimelineEntryResponse as BoundaryPhaseTimelineEntryPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    RunSuitabilityCheck as BoundaryRunSuitabilityCheck,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SpeedStatsResponse as BoundarySpeedStatsPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    StrengthBucketDistributionResponse as BoundaryStrengthBucketDistributionPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    SummaryWarningResponse as BoundarySummaryWarningPayload,
)
from vibesensor.shared.types.history_analysis_contracts import (
    TestPlanStepResponse as BoundaryTestPlanStepPayload,
)


class TypedDictClass(Protocol):
    __required_keys__: frozenset[str]
    __optional_keys__: frozenset[str]


@pytest.mark.parametrize(
    ("name", "boundary_shape", "api_shape"),
    [
        ("AmplitudeMetric", BoundaryAmplitudeMetric, ApiAmplitudeMetric),
        ("AnalysisSummary", BoundaryAnalysisSummary, ApiAnalysisSummaryResponse),
        ("AmpVsPhaseRow", BoundaryAmpVsPhaseRow, ApiAmpVsPhaseRow),
        (
            "DataQualityAccelSanityPayload",
            BoundaryDataQualityAccelSanityPayload,
            ApiDataQualityAccelSanityResponse,
        ),
        (
            "DataQualityOutliersPayload",
            BoundaryDataQualityOutliersPayload,
            ApiDataQualityOutliersResponse,
        ),
        ("DataQualityPayload", BoundaryDataQualityPayload, ApiDataQualityResponse),
        (
            "DataQualityRequiredMissingPctPayload",
            BoundaryDataQualityRequiredMissingPctPayload,
            ApiDataQualityRequiredMissingPctResponse,
        ),
        (
            "DataQualitySpeedCoveragePayload",
            BoundaryDataQualitySpeedCoveragePayload,
            ApiDataQualitySpeedCoverageResponse,
        ),
        (
            "FindingEvidenceMetrics",
            BoundaryFindingEvidenceMetrics,
            ApiFindingEvidenceMetrics,
        ),
        ("FindingPayload", BoundaryFindingPayload, ApiFindingPayload),
        (
            "FreqVsSpeedByFindingSeries",
            BoundaryFreqVsSpeedByFindingSeries,
            ApiFreqVsSpeedByFindingSeries,
        ),
        ("LocationHotspotPayload", BoundaryLocationHotspotPayload, ApiLocationHotspotPayload),
        (
            "LocationIntensitySummaryPayload",
            BoundaryLocationIntensitySummaryPayload,
            ApiLocationIntensitySummaryResponse,
        ),
        (
            "MatchedAmpVsSpeedSeries",
            BoundaryMatchedAmpVsSpeedSeries,
            ApiMatchedAmpVsSpeedSeries,
        ),
        ("MatchedPoint", BoundaryMatchedPoint, ApiMatchedPoint),
        ("OutlierSummaryPayload", BoundaryOutlierSummaryPayload, ApiOutlierSummaryResponse),
        ("PeakTableRow", BoundaryPeakTableRow, ApiPeakTableRow),
        ("PhaseBoundary", BoundaryPhaseBoundary, ApiPhaseBoundary),
        ("PhaseEvidence", BoundaryPhaseEvidence, ApiPhaseEvidence),
        ("PhaseInfoPayload", BoundaryPhaseInfoPayload, ApiPhaseInfoResponse),
        (
            "PhaseIntensityStatsPayload",
            BoundaryPhaseIntensityStatsPayload,
            ApiPhaseIntensityStatsResponse,
        ),
        ("PhaseSegmentOut", BoundaryPhaseSegmentOut, ApiPhaseSegmentOut),
        (
            "PhaseSegmentSummaryPayload",
            BoundaryPhaseSegmentSummaryPayload,
            ApiPhaseSegmentSummaryResponse,
        ),
        ("PhaseSpeedBreakdownRow", BoundaryPhaseSpeedBreakdownRow, ApiPhaseSpeedBreakdownRow),
        (
            "PhaseTimelineEntryPayload",
            BoundaryPhaseTimelineEntryPayload,
            ApiPhaseTimelineEntryResponse,
        ),
        ("PlotDataResult", BoundaryPlotDataResult, ApiPlotDataResult),
        ("RunSuitabilityCheck", BoundaryRunSuitabilityCheck, ApiRunSuitabilityCheck),
        ("SpectrogramResult", BoundarySpectrogramResult, ApiSpectrogramResult),
        ("SpeedBreakdownRow", BoundarySpeedBreakdownRow, ApiSpeedBreakdownRow),
        ("SpeedStatsPayload", BoundarySpeedStatsPayload, ApiSpeedStatsResponse),
        (
            "StrengthBucketDistributionPayload",
            BoundaryStrengthBucketDistributionPayload,
            ApiStrengthBucketDistributionResponse,
        ),
        ("SummaryWarningPayload", BoundarySummaryWarningPayload, ApiSummaryWarningResponse),
        (
            "SuspectedVibrationOrigin",
            BoundarySuspectedVibrationOrigin,
            ApiSuspectedVibrationOriginPayload,
        ),
        ("TestPlanStepPayload", BoundaryTestPlanStepPayload, ApiTestPlanStepResponse),
    ],
)
def test_shared_analysis_history_shapes_have_single_owner_alias(
    name: str,
    boundary_shape: TypedDictClass,
    api_shape: TypedDictClass,
) -> None:
    assert boundary_shape is api_shape, (
        f"{name} should be re-exported from one shared owner instead of "
        "duplicated across boundary and api_models.history modules"
    )


def test_http_history_models_do_not_reexport_shared_summary_wrappers() -> None:
    import vibesensor.adapters.http.models as http_models
    import vibesensor.adapters.http.models.history as history_models

    assert not hasattr(history_models, "AnalysisSummaryCoreResponse")
    assert not hasattr(history_models, "AnalysisSummaryResponse")
    assert not hasattr(http_models, "AnalysisSummaryResponse")
