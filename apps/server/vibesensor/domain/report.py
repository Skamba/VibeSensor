"""Report metadata carrier for a diagnostic run.

``Report`` holds run-level identity and metadata used by the rendering
pipeline.  Finding-level data flows through the raw analysis summary
dicts (``ReportMappingContext``) rather than through this object.
``ReportTemplateData`` in ``report.report_data`` is the PDF-rendering
adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Report",
]


@dataclass(frozen=True, slots=True)
class Report:
    """Run-level metadata carrier consumed by the report rendering pipeline.

    Finding-level data flows through the analysis summary dicts and
    :class:`~vibesensor.adapters.pdf.mapping.ReportMappingContext`, not
    through this object.
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

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id must be non-empty")
        if self.duration_s is not None and self.duration_s < 0:
            raise ValueError("duration_s must be non-negative")
