"""Page geometry calculators for the PDF renderer."""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.units import mm

from .pdf_style import (
    CAR_PANEL_TITLE_RESERVE,
    DATA_TRUST_WIDTH_RATIO,
    EVIDENCE_CAR_PANEL_WIDTH_RATIO,
    GAP,
    MARGIN,
    PANEL_HEADER_H,
)


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


@dataclass(frozen=True)
class CarDiagramLayout:
    panel: PanelLayout
    box_x: float
    box_y: float
    box_w: float
    box_h: float


@dataclass(frozen=True)
class Page2Layout:
    title_bar: PanelLayout
    car_panel: CarDiagramLayout
    pattern_panel: PanelLayout
    peaks_panel: PanelLayout
    observations_panel: PanelLayout | None
    continued_next_steps: PanelLayout | None


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


def build_page1_layout(
    *,
    width: float,
    page_top: float,
    header_content_height: float,
    observed_rows: int,
    y_after_systems_source: float | None = None,
) -> Page1Layout:
    header_columns = build_header_columns_layout(width=width)
    header_height = max(32 * mm, header_columns.meta_top_pad + header_content_height + 4 * mm)
    header = PanelLayout(MARGIN, page_top - header_height, width, header_height)

    obs_step = 4.2 * mm
    obs_content_h = observed_rows * obs_step + 6 * mm
    observed_h = max(32 * mm, PANEL_HEADER_H + obs_content_h + 4 * mm)
    observed = PanelLayout(MARGIN, header.y - GAP - observed_h, width, observed_h)

    systems_h = 58 * mm
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


def build_page2_layout(
    *,
    width: float,
    page_top: float,
    has_transient_findings: bool,
    has_next_steps_continued: bool,
) -> Page2Layout:
    title_h = 12 * mm
    title_bar = PanelLayout(MARGIN, page_top - title_h, width, title_h)
    y_cursor = title_bar.y - GAP

    left_w = width * EVIDENCE_CAR_PANEL_WIDTH_RATIO
    right_w = width - left_w - GAP
    main_h = 118 * mm
    left_y = y_cursor - main_h
    car_panel = PanelLayout(MARGIN, left_y, left_w, main_h)
    inner_pad = 5 * mm
    car_diagram = CarDiagramLayout(
        panel=car_panel,
        box_x=car_panel.x + inner_pad,
        box_y=car_panel.y + inner_pad,
        box_w=car_panel.w - (2 * inner_pad),
        box_h=car_panel.h - CAR_PANEL_TITLE_RESERVE,
    )
    pattern_panel = PanelLayout(MARGIN + left_w + GAP, left_y, right_w, main_h)

    table_h = 53 * mm
    table_y = left_y - GAP - table_h
    peaks_panel = PanelLayout(MARGIN, table_y, width, table_h)

    observations_panel = None
    obs_y_anchor = table_y
    if has_transient_findings:
        obs_h = 24 * mm
        obs_y = table_y - GAP - obs_h
        observations_panel = PanelLayout(MARGIN, obs_y, width, obs_h)
        obs_y_anchor = obs_y

    continued_next_steps = None
    if has_next_steps_continued:
        cont_top = obs_y_anchor - GAP
        cont_bottom = MARGIN + 8 * mm
        if cont_top - cont_bottom > 16 * mm:
            continued_next_steps = PanelLayout(MARGIN, cont_bottom, width, cont_top - cont_bottom)

    return Page2Layout(
        title_bar=title_bar,
        car_panel=car_diagram,
        pattern_panel=pattern_panel,
        peaks_panel=peaks_panel,
        observations_panel=observations_panel,
        continued_next_steps=continued_next_steps,
    )
