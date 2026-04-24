"""Shared report cache key types."""

from __future__ import annotations

__all__ = ["ReportPdfCacheKey"]

ReportPdfCacheKey = tuple[str, str, str | None, int, str, str, str]
