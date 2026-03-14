"""Boundary serializers and decoders for domain-first core models."""

from .diagnostic_case import diagnostic_case_from_summary, test_run_from_summary

__all__ = ["diagnostic_case_from_summary", "test_run_from_summary"]
