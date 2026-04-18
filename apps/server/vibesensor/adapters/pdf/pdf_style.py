"""Shared PDF renderer style, theme, and page geometry."""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

# ── Theme ────────────────────────────────────────────────────────────────────

BMW_LENGTH_MM = 5007.0
BMW_WIDTH_MM = 1894.0

REPORT_COLORS = {
    "brand": "#7c3aed",
    "brand_surface": "#ede9fe",
    "ink": "#1a1c24",
    "border": "#c4c7d0",
    "surface": "#f8f9fb",
    "surface_alt": "#f1f2f6",
    "success": "#0f9d58",
    "warning": "#b7791f",
    "danger": "#c5221f",
    "axis": "#7b8da0",
    "table_row_border": "#dcdfe6",
    "text_primary": "#1a1c24",
    "text_secondary": "#52555e",
    "text_muted": "#6b6e78",
    "card_neutral_bg": "#f8f9fb",
    "card_success_bg": "#e7f5ee",
    "card_warn_bg": "#fef3e0",
    "card_error_bg": "#fce8e6",
    "card_neutral_border": "#c4c7d0",
    "card_success_border": "#a8dab5",
    "card_warn_border": "#f5c98a",
    "card_error_border": "#f5a6a2",
}

# ── Style Constants ──────────────────────────────────────────────────────────

PAGE_SIZE = A4
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 11 * mm

TEXT_CLR = REPORT_COLORS["text_primary"]
SUB_CLR = REPORT_COLORS["text_secondary"]
MUTED_CLR = REPORT_COLORS["text_muted"]
LINE_CLR = REPORT_COLORS["border"]
PANEL_BG = "#ffffff"

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FS_TITLE = 13
FS_H2 = 10
FS_BODY = 7
FS_SMALL = 6
FS_CARD_TITLE = 9.0

R_CARD = 8
GAP = 4 * mm
DATA_TRUST_WIDTH_RATIO = 0.32
PANEL_HEADER_H = 10.5 * mm

_HELVETICA_AVG_CHAR_RATIO = 0.48

# ── Page Geometry ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PanelLayout:
    x: float
    y: float
    w: float
    h: float
