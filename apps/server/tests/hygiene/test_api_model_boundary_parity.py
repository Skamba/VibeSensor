from __future__ import annotations

from typing import Protocol

import pytest
from pydantic import BaseModel

from vibesensor.shared.boundaries.analysis_payload import (
    AmplitudeMetric as BoundaryAmplitudeMetric,
)
from vibesensor.shared.boundaries.analysis_payload import (
    FindingEvidenceMetrics as BoundaryFindingEvidenceMetrics,
)
from vibesensor.shared.boundaries.analysis_payload import (
    FindingPayload as BoundaryFindingPayload,
)
from vibesensor.shared.boundaries.analysis_payload import (
    LocationHotspotPayload as BoundaryLocationHotspotPayload,
)
from vibesensor.shared.boundaries.analysis_payload import MatchedPoint as BoundaryMatchedPoint
from vibesensor.shared.boundaries.analysis_payload import PhaseEvidence as BoundaryPhaseEvidence
from vibesensor.shared.types.api_models.history import AmplitudeMetric as ApiAmplitudeMetric
from vibesensor.shared.types.api_models.history import (
    FindingEvidenceMetrics as ApiFindingEvidenceMetrics,
)
from vibesensor.shared.types.api_models.history import FindingPayload as ApiFindingPayload
from vibesensor.shared.types.api_models.history import (
    LocationHotspotPayload as ApiLocationHotspotPayload,
)
from vibesensor.shared.types.api_models.history import MatchedPoint as ApiMatchedPoint
from vibesensor.shared.types.api_models.history import PhaseEvidence as ApiPhaseEvidence


class TypedDictClass(Protocol):
    __required_keys__: frozenset[str]
    __optional_keys__: frozenset[str]


PydanticModelType = type[BaseModel]


def _typed_dict_fields(typed_dict: TypedDictClass) -> set[str]:
    return set(typed_dict.__required_keys__) | set(typed_dict.__optional_keys__)


def _pydantic_fields(model: PydanticModelType) -> set[str]:
    return set(model.model_fields)


@pytest.mark.parametrize(
    ("name", "typed_dict", "model"),
    [
        ("MatchedPoint", BoundaryMatchedPoint, ApiMatchedPoint),
        ("PhaseEvidence", BoundaryPhaseEvidence, ApiPhaseEvidence),
        ("AmplitudeMetric", BoundaryAmplitudeMetric, ApiAmplitudeMetric),
        ("LocationHotspotPayload", BoundaryLocationHotspotPayload, ApiLocationHotspotPayload),
        (
            "FindingEvidenceMetrics",
            BoundaryFindingEvidenceMetrics,
            ApiFindingEvidenceMetrics,
        ),
        ("FindingPayload", BoundaryFindingPayload, ApiFindingPayload),
    ],
)
def test_boundary_typed_dict_fields_match_http_api_models(
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
