"""Tests for FindingRecord and FindingCollection domain objects."""

from __future__ import annotations

import pytest

from vibesensor.analysis._types import Finding
from vibesensor.analysis.findings import FindingCollection, FindingRecord


# ---------------------------------------------------------------------------
# Fixtures: minimal Finding dicts
# ---------------------------------------------------------------------------


def _ref_finding(finding_id: str = "REF_SPEED") -> Finding:
    return {
        "finding_id": finding_id,
        "suspected_source": "unknown",
        "evidence_summary": {"_i18n_key": "TEST"},
        "frequency_hz_or_order": "n/a",
        "amplitude_metric": {"name": "n/a", "value": None, "units": "n/a", "definition": "n/a"},
        "confidence": None,
        "quick_checks": [],
    }


def _diag_finding(
    finding_id: str = "F_ORDER",
    confidence: float = 0.65,
    source: str = "wheel/tire",
    ranking_score: float = 1.0,
    location: str = "front_left",
) -> Finding:
    return {
        "finding_id": finding_id,
        "suspected_source": source,
        "evidence_summary": {"_i18n_key": "TEST"},
        "frequency_hz_or_order": "1x wheel",
        "amplitude_metric": {
            "name": "vibration_strength_db",
            "value": 25.0,
            "units": "dB",
            "definition": {"_i18n_key": "METRIC"},
        },
        "confidence": confidence,
        "quick_checks": [],
        "_ranking_score": ranking_score,
        "strongest_location": location,
    }


def _info_finding(finding_id: str = "F_PEAK", confidence: float = 0.10) -> Finding:
    f = _diag_finding(finding_id=finding_id, confidence=confidence)
    f["severity"] = "info"
    f["suspected_source"] = "transient_impact"
    return f


# ===========================================================================
# FindingRecord
# ===========================================================================


class TestFindingRecord:
    def test_finding_id(self) -> None:
        rec = FindingRecord(_diag_finding(finding_id="F_ORDER"))
        assert rec.finding_id == "F_ORDER"

    def test_is_reference(self) -> None:
        assert FindingRecord(_ref_finding()).is_reference is True
        assert FindingRecord(_diag_finding()).is_reference is False

    def test_is_informational(self) -> None:
        assert FindingRecord(_info_finding()).is_informational is True
        assert FindingRecord(_diag_finding()).is_informational is False

    def test_is_diagnostic(self) -> None:
        assert FindingRecord(_diag_finding()).is_diagnostic is True
        assert FindingRecord(_ref_finding()).is_diagnostic is False
        assert FindingRecord(_info_finding()).is_diagnostic is False

    def test_confidence_default(self) -> None:
        rec = FindingRecord(_ref_finding())
        assert rec.confidence == 0.0

    def test_confidence_value(self) -> None:
        rec = FindingRecord(_diag_finding(confidence=0.75))
        assert rec.confidence == 0.75

    def test_source_normalized(self) -> None:
        f = _diag_finding(source="  Wheel/Tire  ")
        assert FindingRecord(f).source_normalized == "wheel/tire"

    def test_strongest_location(self) -> None:
        rec = FindingRecord(_diag_finding(location="front_left"))
        assert rec.strongest_location == "front_left"

    def test_ranking_score(self) -> None:
        rec = FindingRecord(_diag_finding(ranking_score=2.5))
        assert rec.ranking_score == 2.5

    def test_assign_id_mutates_underlying_dict(self) -> None:
        finding = _diag_finding()
        rec = FindingRecord(finding)
        rec.assign_id("F001")
        assert finding["finding_id"] == "F001"

    def test_data_returns_underlying_dict(self) -> None:
        finding = _diag_finding()
        rec = FindingRecord(finding)
        assert rec.data is finding


# ===========================================================================
# FindingCollection
# ===========================================================================


class TestFindingCollection:
    def test_len(self) -> None:
        coll = FindingCollection([_diag_finding(), _ref_finding()])
        assert len(coll) == 2

    def test_iter(self) -> None:
        findings = [_diag_finding(), _ref_finding()]
        coll = FindingCollection(findings)
        assert list(coll) == findings

    def test_references(self) -> None:
        findings = [_ref_finding("REF_SPEED"), _diag_finding(), _ref_finding("REF_ENGINE")]
        coll = FindingCollection(findings)
        refs = coll.references()
        assert len(refs) == 2
        assert all(str(f["finding_id"]).startswith("REF_") for f in refs)

    def test_diagnostics(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        diags = coll.diagnostics()
        assert len(diags) == 1
        assert diags[0]["suspected_source"] == "wheel/tire"

    def test_informational(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        infos = coll.informational()
        assert len(infos) == 1
        assert infos[0].get("severity") == "info"

    def test_non_reference(self) -> None:
        findings = [_ref_finding(), _diag_finding(), _info_finding()]
        coll = FindingCollection(findings)
        non_ref = coll.non_reference()
        assert len(non_ref) == 2

    def test_finalize_ordering(self) -> None:
        """References come first, then diagnostics by confidence, then informational."""
        ref = _ref_finding()
        diag_high = _diag_finding(confidence=0.80, ranking_score=2.0)
        diag_low = _diag_finding(confidence=0.30, ranking_score=1.0)
        info = _info_finding(confidence=0.10)
        coll = FindingCollection([diag_low, info, ref, diag_high])
        ordered = coll.finalize()
        assert len(ordered) == 4
        # Reference first
        assert str(ordered[0]["finding_id"]).startswith("REF_")
        # Then high-confidence diagnostic
        assert ordered[1]["confidence"] == 0.80
        # Then low-confidence diagnostic
        assert ordered[2]["confidence"] == 0.30
        # Then informational
        assert ordered[3].get("severity") == "info"

    def test_finalize_assigns_sequential_ids(self) -> None:
        ref = _ref_finding("REF_SPEED")
        d1 = _diag_finding(confidence=0.80)
        d2 = _diag_finding(confidence=0.40)
        info = _info_finding()
        coll = FindingCollection([d2, info, ref, d1])
        ordered = coll.finalize()
        # Reference keeps its original ID
        assert ordered[0]["finding_id"] == "REF_SPEED"
        # Non-reference findings get sequential F### IDs
        assert ordered[1]["finding_id"] == "F001"
        assert ordered[2]["finding_id"] == "F002"
        assert ordered[3]["finding_id"] == "F003"

    def test_finalize_empty(self) -> None:
        coll = FindingCollection([])
        assert coll.finalize() == []

    def test_items_property(self) -> None:
        findings = [_diag_finding()]
        coll = FindingCollection(findings)
        assert coll.items is findings
