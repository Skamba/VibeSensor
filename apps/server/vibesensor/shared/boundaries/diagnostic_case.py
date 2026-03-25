"""Decode persisted diagnostic summaries into domain DiagnosticCase models."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import Car
from vibesensor.domain.diagnostic_case import DiagnosticCase, Symptom
from vibesensor.shared.boundaries import test_run_reconstruction as _test_run_reconstruction


def _require_authoritative_case_id(summary: Mapping[str, object]) -> str:
    case_id = summary.get("case_id")
    if isinstance(case_id, str):
        normalized_case_id = case_id.strip()
        if normalized_case_id:
            return normalized_case_id
    raise ValueError("Cannot decode DiagnosticCase from summary without authoritative case_id")


def diagnostic_case_from_summary(summary: Mapping[str, object]) -> DiagnosticCase:
    metadata = summary.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    car = Car.from_metadata(meta)
    symptoms = (Symptom.from_metadata(meta),)
    test_run = _test_run_reconstruction.test_run_from_summary(summary)
    case = DiagnosticCase(
        case_id=_require_authoritative_case_id(summary),
        car=car,
        symptoms=symptoms,
        test_plan=test_run.test_plan,
    )
    return case.add_run(test_run)
