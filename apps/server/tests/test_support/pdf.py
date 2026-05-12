from __future__ import annotations

from io import BytesIO


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF byte string using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)
