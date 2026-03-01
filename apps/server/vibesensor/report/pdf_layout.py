"""Aspect-ratio and geometry helpers for PDF report layout.

Pure-maths utilities that keep the drawing code in ``pdf_builder.py``
focused on content rather than layout arithmetic.
"""

from __future__ import annotations


def fit_rect_preserve_aspect(
    src_w: float,
    src_h: float,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) fitted inside box while preserving src aspect."""
    if src_w <= 0 or src_h <= 0:
        return box_x, box_y, box_w, box_h
    src_ratio = src_w / src_h
    box_ratio = box_w / box_h if box_h else src_ratio
    if box_ratio > src_ratio:
        h = box_h
        w = h * src_ratio
        x = box_x + (box_w - w) / 2
        y = box_y
    else:
        w = box_w
        h = w / src_ratio
        x = box_x
        y = box_y + (box_h - h) / 2
    return x, y, w, h


def assert_aspect_preserved(
    src_w: float,
    src_h: float,
    drawn_w: float,
    drawn_h: float,
    tolerance: float = 0.03,
) -> None:
    """Raise if aspect ratio deviates more than *tolerance* (3 %)."""
    if src_w <= 0 or src_h <= 0 or drawn_w <= 0 or drawn_h <= 0:
        raise AssertionError("Invalid dimensions for aspect ratio check")
    src_ratio = src_w / src_h
    drawn_ratio = drawn_w / drawn_h
    delta = abs(drawn_ratio - src_ratio) / src_ratio
    if delta > tolerance:
        raise AssertionError(
            f"Car visual aspect ratio distorted. src={src_ratio:.4f}, "
            f"drawn={drawn_ratio:.4f}, delta={delta:.2%}"
        )
