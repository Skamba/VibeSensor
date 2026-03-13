"""The assembled output of a diagnostic run.

``Report`` is the primary domain object for a rendered or ready-to-render
report.  ``ReportTemplateData`` in ``report.report_data`` remains as the
PDF-rendering adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from .finding import Finding

__all__ = [
    "Report",
]


@dataclass(frozen=True, slots=True)
class Report:
    """The assembled output of a diagnostic run.

    This is the primary domain object for a rendered or ready-to-render
    report.  ``ReportTemplateData`` in ``report.report_data`` remains as
    the PDF-rendering adapter.

    The :attr:`findings` tuple holds domain :class:`Finding` objects
    extracted from the analysis summary, giving the report first-class
    access to its diagnostic conclusions.
    """

    run_id: str
    title: str = ""
    lang: str = "en"
    car_name: str | None = None
    car_type: str | None = None
    report_date: str | None = None
    duration_s: float | None = None
    sample_count: int = 0
    sensor_count: int = 0
    findings: tuple[Finding, ...] = ()

    # -- queries -----------------------------------------------------------

    @property
    def finding_count(self) -> int:
        """Total number of findings (derived from findings tuple)."""
        return len(self.findings)

    # -- queries -----------------------------------------------------------

    @property
    def has_findings(self) -> bool:
        """Whether this report contains any findings."""
        return bool(self.findings)

    @property
    def diagnostic_findings(self) -> list[Finding]:
        """Return only diagnostic (non-reference, non-info) findings."""
        return [f for f in self.findings if f.is_diagnostic]

    @property
    def primary_finding(self) -> Finding | None:
        """The top-ranked diagnostic finding, or ``None``."""
        diags = self.diagnostic_findings
        return diags[0] if diags else None

    @property
    def is_empty(self) -> bool:
        """Whether the report has no diagnostic content."""
        return not self.diagnostic_findings
