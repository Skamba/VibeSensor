"""Shared PDF renderer style and layout constants."""

from __future__ import annotations

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from .theme import REPORT_COLORS

PAGE_SIZE = A4
PAGE_W, PAGE_H = PAGE_SIZE
MARGIN = 11 * mm

TEXT_CLR = REPORT_COLORS["text_primary"]
SUB_CLR = REPORT_COLORS["text_secondary"]
MUTED_CLR = REPORT_COLORS["text_muted"]
LINE_CLR = REPORT_COLORS["border"]
PANEL_BG = "#ffffff"
SOFT_BG = REPORT_COLORS["surface"]
WARN_CLR = REPORT_COLORS["warning"]

FONT = "Helvetica"
FONT_B = "Helvetica-Bold"
FS_TITLE = 12
FS_H2 = 9
FS_BODY = 7
FS_SMALL = 6
FS_CARD_TITLE = 8.0

R_CARD = 6
GAP = 4 * mm
OBSERVED_LABEL_W = 28 * mm
DATA_TRUST_WIDTH_RATIO = 0.32
DATA_TRUST_LABEL_W = 27 * mm
EVIDENCE_CAR_PANEL_WIDTH_RATIO = 0.50
DISCLAIMER_Y_OFFSET = 5.5 * mm
CAR_PANEL_TITLE_RESERVE = 18 * mm
PANEL_HEADER_H = 10.5 * mm

_HELVETICA_AVG_CHAR_RATIO = 0.48
