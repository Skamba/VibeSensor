"""Canonical finding-presentation codecs for prepared report boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import Finding, TestRun

__all__ = [
    "FindingPresentation",
    "PreparedReportFindings",
    "prepare_report_findings",
]


@dataclass(frozen=True)
class FindingPresentation:
    """Presentation-ready snapshot of a domain Finding for the PDF renderer."""

    suspected_source: str = ""
    severity: str = ""
    strongest_location: str | None = None
    peak_classification: str = ""
    order: str = ""
    frequency_hz: float | None = None
    effective_confidence: float = 0.0


@dataclass(frozen=True, slots=True)
class PreparedReportFindings:
    """Prepared finding presentations grouped by report role."""

    all_findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]


def prepare_report_findings(test_run: TestRun) -> PreparedReportFindings:
    """Convert report-facing finding presentations once at the boundary layer."""

    return PreparedReportFindings(
        all_findings=tuple(_finding_to_presentation(finding) for finding in test_run.findings),
        top_causes=tuple(
            _finding_to_presentation(finding) for finding in test_run.effective_top_causes()
        ),
    )


def _finding_to_presentation(finding: Finding) -> FindingPresentation:
    return FindingPresentation(
        suspected_source=str(finding.suspected_source),
        severity=finding.severity,
        strongest_location=finding.strongest_location,
        peak_classification=finding.peaks.classification,
        order=finding.order,
        frequency_hz=finding.frequency_hz,
        effective_confidence=finding.effective_confidence,
    )
