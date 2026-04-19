"""Direct behavior tests for engine alias suppression."""

from __future__ import annotations

from test_support.findings import make_finding

from vibesensor.use_cases.diagnostics.orders.heuristics import (
    suppress_engine_aliases as _suppress_engine_aliases,
)


class TestSuppressEngineAliases:
    """Direct unit tests for _suppress_engine_aliases."""

    def test_no_wheel_no_suppression(self) -> None:
        findings = [
            (1.0, make_finding(suspected_source="engine", confidence=0.60, ranking_score=1.0)),
            (0.5, make_finding(suspected_source="driveshaft", confidence=0.40, ranking_score=0.5)),
        ]
        result = _suppress_engine_aliases(findings)
        assert any(str(f.suspected_source) == "engine" for f in result), (
            "Engine finding should survive when no wheel finding exists"
        )

    def test_engine_suppressed_by_stronger_wheel(self) -> None:
        findings = [
            (1.0, make_finding(suspected_source="wheel/tire", confidence=0.70, ranking_score=1.0)),
            (0.8, make_finding(suspected_source="engine", confidence=0.65, ranking_score=0.8)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if str(f.suspected_source) == "engine"]
        if engine_findings:
            assert engine_findings[0].effective_confidence < 0.65

    def test_strong_engine_not_suppressed(self) -> None:
        findings = [
            (0.3, make_finding(suspected_source="wheel/tire", confidence=0.30, ranking_score=0.3)),
            (1.0, make_finding(suspected_source="engine", confidence=0.90, ranking_score=1.0)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if str(f.suspected_source) == "engine"]
        assert engine_findings, "Strong engine should survive weak wheel"

    def test_empty_input(self) -> None:
        assert _suppress_engine_aliases([]) == []

    def test_output_capped_at_5(self) -> None:
        findings = [
            (
                i,
                make_finding(
                    suspected_source="wheel/tire",
                    confidence=0.50 + i * 0.05,
                    ranking_score=float(i),
                ),
            )
            for i in range(7)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) <= 5
