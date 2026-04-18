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


@dataclass(frozen=True)
class HeaderColumnsLayout:
    meta_x: float
    meta_right: float
    left_col_w: float
    right_col_w: float
    meta_top_pad: float
    meta_row_gap: float


@dataclass(frozen=True)
class BottomRowLayout:
    next_steps: PanelLayout
    data_trust: PanelLayout


@dataclass(frozen=True)
class Page1Layout:
    header: PanelLayout
    header_columns: HeaderColumnsLayout
    observed: PanelLayout
    systems: PanelLayout
    bottom: BottomRowLayout


def build_header_columns_layout(*, width: float) -> HeaderColumnsLayout:
    meta_x = MARGIN + 4 * mm
    meta_right = meta_x + 95 * mm
    meta_col_gap = 6 * mm
    return HeaderColumnsLayout(
        meta_x=meta_x,
        meta_right=meta_right,
        left_col_w=max(30 * mm, meta_right - meta_x - meta_col_gap),
        right_col_w=width - (meta_right - MARGIN) - 8 * mm,
        meta_top_pad=12 * mm,
        meta_row_gap=1 * mm,
    )


def show_observed_signature_location(*, certainty_tier_key: str, system_card_count: int) -> bool:
    """Keep strongest-sensor context on page 1 when the systems panel cannot show cards."""
    return certainty_tier_key == "A" or system_card_count == 0


def observed_signature_row_count(
    *,
    certainty_tier_key: str,
    system_card_count: int,
    has_certainty_reason: bool,
) -> int:
    return (
        4
        + int(
            show_observed_signature_location(
                certainty_tier_key=certainty_tier_key,
                system_card_count=system_card_count,
            )
        )
        + int(has_certainty_reason)
        + int(certainty_tier_key == "A")
    )


def build_page1_layout(
    *,
    width: float,
    page_top: float,
    header_content_height: float,
    observed_rows: int,
    y_after_systems_source: float | None = None,
) -> Page1Layout:
    header_columns = build_header_columns_layout(width=width)
    header_height = max(28 * mm, header_columns.meta_top_pad + header_content_height + 4 * mm)
    header = PanelLayout(MARGIN, page_top - header_height, width, header_height)

    obs_step = 4.2 * mm
    obs_content_h = observed_rows * obs_step + 6 * mm
    observed_h = max(44 * mm, PANEL_HEADER_H + obs_content_h + 8 * mm)
    observed = PanelLayout(MARGIN, header.y - GAP - observed_h, width, observed_h)

    systems_h = 46 * mm
    systems = PanelLayout(MARGIN, observed.y - GAP - systems_h, width, systems_h)

    y_cursor = systems.y - GAP if y_after_systems_source is None else y_after_systems_source
    footer_reserve = 8 * mm
    available_h = y_cursor - MARGIN - footer_reserve
    next_h = max(44 * mm, available_h)
    trust_w = width * DATA_TRUST_WIDTH_RATIO
    next_w = width - trust_w - GAP
    next_y = y_cursor - next_h
    bottom = BottomRowLayout(
        next_steps=PanelLayout(MARGIN, next_y, next_w, next_h),
        data_trust=PanelLayout(MARGIN + next_w + GAP, next_y, trust_w, next_h),
    )
    return Page1Layout(
        header=header,
        header_columns=header_columns,
        observed=observed,
        systems=systems,
        bottom=bottom,
    )
