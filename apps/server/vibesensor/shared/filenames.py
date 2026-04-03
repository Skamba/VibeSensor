"""Filename sanitization helpers shared across HTTP and report boundaries."""

from __future__ import annotations

import re

__all__ = ["safe_filename"]

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


def safe_filename(name: str) -> str:
    """Sanitize *name* for use in filenames and Content-Disposition headers."""
    cleaned = _SAFE_FILENAME_RE.sub("_", name)[:200].lstrip(".")
    return cleaned or "download"
