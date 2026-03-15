"""PDF rendering adapter package."""

from __future__ import annotations

from typing import Any

__all__ = ["build_report_pdf"]


def __getattr__(name: str) -> Any:
    if name == "build_report_pdf":
        from .pdf_engine import build_report_pdf

        return build_report_pdf
    raise AttributeError(name)
