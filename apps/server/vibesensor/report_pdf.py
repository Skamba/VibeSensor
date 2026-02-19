"""Backward-compat shim – real code lives in vibesensor.report.pdf_builder."""

from .report.pdf_builder import build_report_pdf  # noqa: F401

__all__ = ["build_report_pdf"]
