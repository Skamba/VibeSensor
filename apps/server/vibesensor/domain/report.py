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

    # -- factories ---------------------------------------------------------

    @classmethod
    def from_summary(cls, summary: dict[str, object]) -> Report:
        """Create a domain Report from a ``SummaryData`` dict.

        Extracts the key metadata fields from the analysis summary to build
        a high-level domain view of the report, including domain
        :class:`Finding` objects for each finding in the summary.
        """
        meta = summary.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}

        car_cfg = meta.get("car")
        car_name: str | None = None
        car_type: str | None = None
        if isinstance(car_cfg, dict):
            raw_name = car_cfg.get("name")
            car_name = str(raw_name) if raw_name else None
            raw_type = car_cfg.get("car_type")
            car_type = str(raw_type) if raw_type else None

        raw_findings = summary.get("findings")
        finding_list: list[Finding] = []
        if isinstance(raw_findings, list):
            for item in raw_findings:
                if isinstance(item, dict):
                    finding_list.append(Finding.from_payload(item))

        rows = summary.get("rows")
        sample_count = int(rows) if isinstance(rows, (int, float, str)) else 0

        sensor_count_raw = summary.get("sensor_count_used")
        sensor_count = (
            int(sensor_count_raw) if isinstance(sensor_count_raw, (int, float, str)) else 0
        )

        duration_s_raw = summary.get("duration_s")
        duration_s: float | None = None
        if duration_s_raw is not None:
            try:
                duration_s = float(duration_s_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                pass

        report_date = summary.get("report_date")
        report_date_str = str(report_date) if isinstance(report_date, str) else None

        return cls(
            run_id=str(summary.get("run_id", "")),
            lang=str(summary.get("lang", "en")),
            car_name=car_name,
            car_type=car_type,
            report_date=report_date_str,
            duration_s=duration_s,
            sample_count=sample_count,
            sensor_count=sensor_count,
            findings=tuple(finding_list),
        )
