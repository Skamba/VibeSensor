"""Canonical boundary package for analysis summary and persistence payloads."""

from .contracts import AnalysisResultLike
from .persisted import (
    persisted_analysis_from_storage_json_object,
    persisted_analysis_to_storage_json_object,
)
from .projection import project_analysis_summary, project_persisted_analysis
from .summary import analysis_result_to_summary, analysis_summary_with_warnings

__all__ = [
    "AnalysisResultLike",
    "analysis_result_to_summary",
    "analysis_summary_with_warnings",
    "persisted_analysis_from_storage_json_object",
    "persisted_analysis_to_storage_json_object",
    "project_analysis_summary",
    "project_persisted_analysis",
]
