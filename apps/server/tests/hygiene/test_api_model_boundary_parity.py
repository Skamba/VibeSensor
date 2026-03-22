from __future__ import annotations

from typing import Protocol

import pytest
from pydantic import BaseModel

from vibesensor.shared.boundaries.analysis_payload import (
    AmplitudeMetric as BoundaryAmplitudeMetric,
)
from vibesensor.shared.boundaries.analysis_payload import (
    AmpVsPhaseRow as BoundaryAmpVsPhaseRow,
)
from vibesensor.shared.boundaries.analysis_payload import (
    FindingEvidenceMetrics as BoundaryFindingEvidenceMetrics,
)
from vibesensor.shared.boundaries.analysis_payload import (
    FindingPayload as BoundaryFindingPayload,
)
from vibesensor.shared.boundaries.analysis_payload import (
    FreqVsSpeedByFindingSeries as BoundaryFreqVsSpeedByFindingSeries,
)
from vibesensor.shared.boundaries.analysis_payload import (
    LocationHotspotPayload as BoundaryLocationHotspotPayload,
)
from vibesensor.shared.boundaries.analysis_payload import (
    MatchedAmpVsSpeedSeries as BoundaryMatchedAmpVsSpeedSeries,
)
from vibesensor.shared.boundaries.analysis_payload import (
    MatchedPoint as BoundaryMatchedPoint,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PeakTableRow as BoundaryPeakTableRow,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PhaseBoundary as BoundaryPhaseBoundary,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PhaseEvidence as BoundaryPhaseEvidence,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PhaseSegmentOut as BoundaryPhaseSegmentOut,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PhaseSpeedBreakdownRow as BoundaryPhaseSpeedBreakdownRow,
)
from vibesensor.shared.boundaries.analysis_payload import (
    PlotDataResult as BoundaryPlotDataResult,
)
from vibesensor.shared.boundaries.analysis_payload import (
    RunSuitabilityCheck as BoundaryRunSuitabilityCheck,
)
from vibesensor.shared.boundaries.analysis_payload import (
    SpectrogramResult as BoundarySpectrogramResult,
)
from vibesensor.shared.boundaries.analysis_payload import (
    SpeedBreakdownRow as BoundarySpeedBreakdownRow,
)
from vibesensor.shared.types.api_models.history import (
    AmplitudeMetric as ApiAmplitudeMetric,
)
from vibesensor.shared.types.api_models.history import (
    AmpVsPhaseRow as ApiAmpVsPhaseRow,
)
from vibesensor.shared.types.api_models.history import (
    FindingEvidenceMetrics as ApiFindingEvidenceMetrics,
)
from vibesensor.shared.types.api_models.history import (
    FindingPayload as ApiFindingPayload,
)
from vibesensor.shared.types.api_models.history import (
    FreqVsSpeedByFindingSeries as ApiFreqVsSpeedByFindingSeries,
)
from vibesensor.shared.types.api_models.history import (
    LocationHotspotPayload as ApiLocationHotspotPayload,
)
from vibesensor.shared.types.api_models.history import (
    MatchedAmpVsSpeedSeries as ApiMatchedAmpVsSpeedSeries,
)
from vibesensor.shared.types.api_models.history import (
    MatchedPoint as ApiMatchedPoint,
)
from vibesensor.shared.types.api_models.history import (
    PeakTableRow as ApiPeakTableRow,
)
from vibesensor.shared.types.api_models.history import (
    PhaseBoundary as ApiPhaseBoundary,
)
from vibesensor.shared.types.api_models.history import (
    PhaseEvidence as ApiPhaseEvidence,
)
from vibesensor.shared.types.api_models.history import (
    PhaseSegmentOut as ApiPhaseSegmentOut,
)
from vibesensor.shared.types.api_models.history import (
    PhaseSpeedBreakdownRow as ApiPhaseSpeedBreakdownRow,
)
from vibesensor.shared.types.api_models.history import (
    PlotDataResult as ApiPlotDataResult,
)
from vibesensor.shared.types.api_models.history import (
    RunSuitabilityCheck as ApiRunSuitabilityCheck,
)
from vibesensor.shared.types.api_models.history import (
    SpectrogramResult as ApiSpectrogramResult,
)
from vibesensor.shared.types.api_models.history import (
    SpeedBreakdownRow as ApiSpeedBreakdownRow,
)


class TypedDictClass(Protocol):
    __required_keys__: frozenset[str]
    __optional_keys__: frozenset[str]


PydanticModelType = type[BaseModel]


def _typed_dict_fields(typed_dict: TypedDictClass) -> set[str]:
    return set(typed_dict.__required_keys__) | set(typed_dict.__optional_keys__)


def _pydantic_fields(model: PydanticModelType) -> set[str]:
    return set(model.model_fields)


@pytest.mark.parametrize(
    ("name", "boundary_shape", "api_shape"),
    [
        ("AmpVsPhaseRow", BoundaryAmpVsPhaseRow, ApiAmpVsPhaseRow),
        (
            "FindingEvidenceMetrics",
            BoundaryFindingEvidenceMetrics,
            ApiFindingEvidenceMetrics,
        ),
        (
            "FreqVsSpeedByFindingSeries",
            BoundaryFreqVsSpeedByFindingSeries,
            ApiFreqVsSpeedByFindingSeries,
        ),
        ("LocationHotspotPayload", BoundaryLocationHotspotPayload, ApiLocationHotspotPayload),
        (
            "MatchedAmpVsSpeedSeries",
            BoundaryMatchedAmpVsSpeedSeries,
            ApiMatchedAmpVsSpeedSeries,
        ),
        ("MatchedPoint", BoundaryMatchedPoint, ApiMatchedPoint),
        ("PeakTableRow", BoundaryPeakTableRow, ApiPeakTableRow),
        ("PhaseBoundary", BoundaryPhaseBoundary, ApiPhaseBoundary),
        ("PhaseEvidence", BoundaryPhaseEvidence, ApiPhaseEvidence),
        ("PhaseSegmentOut", BoundaryPhaseSegmentOut, ApiPhaseSegmentOut),
        ("PhaseSpeedBreakdownRow", BoundaryPhaseSpeedBreakdownRow, ApiPhaseSpeedBreakdownRow),
        ("PlotDataResult", BoundaryPlotDataResult, ApiPlotDataResult),
        ("SpectrogramResult", BoundarySpectrogramResult, ApiSpectrogramResult),
        ("SpeedBreakdownRow", BoundarySpeedBreakdownRow, ApiSpeedBreakdownRow),
    ],
)
def test_exact_shared_shapes_have_single_owner_alias(
    name: str,
    boundary_shape: TypedDictClass,
    api_shape: TypedDictClass,
) -> None:
    assert boundary_shape is api_shape, (
        f"{name} should be re-exported from one shared owner instead of "
        "duplicated in analysis_payload and api_models.history"
    )


@pytest.mark.parametrize(
    ("name", "typed_dict", "model"),
    [
        ("AmplitudeMetric", BoundaryAmplitudeMetric, ApiAmplitudeMetric),
        ("FindingPayload", BoundaryFindingPayload, ApiFindingPayload),
        ("RunSuitabilityCheck", BoundaryRunSuitabilityCheck, ApiRunSuitabilityCheck),
    ],
)
def test_remaining_boundary_typed_dict_fields_match_http_api_models(
    name: str,
    typed_dict: TypedDictClass,
    model: PydanticModelType,
) -> None:
    boundary_fields = _typed_dict_fields(typed_dict)
    api_fields = _pydantic_fields(model)

    assert api_fields == boundary_fields, (
        f"{name} drifted between shared.boundaries.analysis_payload and "
        f"shared.types.api_models.history: "
        f"typed_dict_only={sorted(boundary_fields - api_fields)}, "
        f"api_model_only={sorted(api_fields - boundary_fields)}"
    )
