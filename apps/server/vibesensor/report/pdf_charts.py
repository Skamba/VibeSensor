"""PDF report chart functions – line plots and spectrograms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..report_analysis import _as_float
from ..report_theme import REPORT_COLORS, REPORT_PLOT_COLORS
from .pdf_helpers import color_blend, downsample

if TYPE_CHECKING:
    from collections.abc import Callable


def line_plot(
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: list[tuple[str, str, list[tuple[float, float]]]],
    content_width: float,
    tr: Callable[..., str],
    width: float | None = None,
    height: int = 195,
) -> Any:
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    plot_width = width if width is not None else content_width
    drawing = Drawing(plot_width, height)
    plot_x0 = 52
    plot_y0 = 30
    plot_w = plot_width - 88
    plot_h = height - 60

    drawing.add(
        String(
            8,
            height - 16,
            title,
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        )
    )

    active_series = [(name, color, downsample(points)) for name, color, points in series if points]
    if not active_series:
        drawing.add(
            String(
                8,
                height - 32,
                tr("PLOT_NO_DATA_AVAILABLE"),
                fontSize=8,
                fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
            )
        )
        return drawing

    all_points = [point for _name, _color, points in active_series for point in points]
    x_min = min(point[0] for point in all_points)
    x_max = max(point[0] for point in all_points)
    y_min = min(point[1] for point in all_points)
    y_max = max(point[1] for point in all_points)
    if abs(x_max - x_min) < 1e-9:
        x_max = x_min + 1.0
    if abs(y_max - y_min) < 1e-9:
        y_max = y_min + 1.0
    y_min = min(0.0, y_min)

    def map_x(x_val: float) -> float:
        return plot_x0 + ((x_val - x_min) / (x_max - x_min) * plot_w)

    def map_y(y_val: float) -> float:
        return plot_y0 + ((y_val - y_min) / (y_max - y_min) * plot_h)

    for idx in range(6):
        frac = idx / 5.0
        gx = plot_x0 + (frac * plot_w)
        gy = plot_y0 + (frac * plot_h)
        drawing.add(
            Line(
                gx,
                plot_y0,
                gx,
                plot_y0 + plot_h,
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.4,
            )
        )
        drawing.add(
            Line(
                plot_x0,
                gy,
                plot_x0 + plot_w,
                gy,
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.4,
            )
        )
        drawing.add(
            String(
                gx - 10,
                plot_y0 - 12,
                f"{(x_min + frac * (x_max - x_min)):.0f}",
                fontSize=6.5,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                plot_x0 - 30,
                gy - 2,
                f"{(y_min + frac * (y_max - y_min)):.1f}",
                fontSize=6.5,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )

    drawing.add(
        Line(
            plot_x0,
            plot_y0,
            plot_x0 + plot_w,
            plot_y0,
            strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
        )
    )
    drawing.add(
        Line(
            plot_x0,
            plot_y0,
            plot_x0,
            plot_y0 + plot_h,
            strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
        )
    )
    drawing.add(
        String(
            plot_x0 + (plot_w / 2) - 18,
            6,
            x_label,
            fontSize=7,
            fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
        )
    )
    drawing.add(
        String(
            8,
            plot_y0 + (plot_h / 2),
            y_label,
            fontSize=7,
            fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
        )
    )

    legend_x = plot_x0 + 4
    legend_y = height - 30
    for idx, (name, color, points) in enumerate(active_series):
        flat_points: list[float] = []
        for x_val, y_val in points:
            flat_points.append(map_x(x_val))
            flat_points.append(map_y(y_val))
        drawing.add(PolyLine(flat_points, strokeColor=colors.HexColor(color), strokeWidth=1.3))
        drawing.add(
            Rect(
                legend_x + (idx * 150),
                legend_y - 2,
                8,
                8,
                fillColor=colors.HexColor(color),
                strokeColor=colors.HexColor(color),
            )
        )
        drawing.add(
            String(
                legend_x + 11 + (idx * 150),
                legend_y - 1,
                name,
                fontSize=7,
                fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
            )
        )
    return drawing


def spectrogram_plot(
    title: str,
    spectrogram: dict[str, object],
    width: float,
    *,
    tr: Callable[..., str],
    height: int = 170,
) -> Any:
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors

    drawing = Drawing(width, height)
    drawing.add(
        String(
            8,
            height - 15,
            title,
            fontName="Helvetica-Bold",
            fontSize=9,
            fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        )
    )

    x_bins = spectrogram.get("x_bins", []) if isinstance(spectrogram, dict) else []
    y_bins = spectrogram.get("y_bins", []) if isinstance(spectrogram, dict) else []
    cells = spectrogram.get("cells", []) if isinstance(spectrogram, dict) else []
    max_amp = _as_float(spectrogram.get("max_amp")) if isinstance(spectrogram, dict) else 0.0

    if (
        not isinstance(x_bins, list)
        or not isinstance(y_bins, list)
        or not isinstance(cells, list)
        or not x_bins
        or not y_bins
        or not cells
        or not max_amp
    ):
        drawing.add(
            String(
                8,
                height - 32,
                tr("PLOT_NO_DATA_AVAILABLE"),
                fontSize=8,
                fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
            )
        )
        return drawing

    plot_x0 = 44
    plot_y0 = 28
    plot_w = width - 62
    plot_h = height - 52
    cols = max(1, len(x_bins))
    rows = max(1, len(y_bins))
    cell_w = plot_w / cols
    cell_h = plot_h / rows

    for yi, row in enumerate(cells):
        if not isinstance(row, list):
            continue
        for xi, amp in enumerate(row):
            level = ((_as_float(amp) or 0.0) / max_amp) if max_amp and max_amp > 0 else 0.0
            color_hex = color_blend(
                REPORT_COLORS["surface_alt"], REPORT_PLOT_COLORS["vibration"], level
            )
            drawing.add(
                Rect(
                    plot_x0 + (xi * cell_w),
                    plot_y0 + (yi * cell_h),
                    max(0.1, cell_w),
                    max(0.1, cell_h),
                    fillColor=colors.HexColor(color_hex),
                    strokeColor=colors.HexColor(REPORT_COLORS["surface_alt"]),
                    strokeWidth=0.2,
                )
            )

    drawing.add(
        Line(
            plot_x0,
            plot_y0,
            plot_x0 + plot_w,
            plot_y0,
            strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
        )
    )
    drawing.add(
        Line(
            plot_x0,
            plot_y0,
            plot_x0,
            plot_y0 + plot_h,
            strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
        )
    )

    x_label_key = str(spectrogram.get("x_label_key") or "TIME_S")
    drawing.add(
        String(
            plot_x0 + (plot_w / 2) - 18,
            8,
            tr(x_label_key),
            fontSize=6.5,
            fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
        )
    )
    drawing.add(
        String(
            8,
            plot_y0 + (plot_h / 2),
            tr("FREQUENCY_HZ"),
            fontSize=6.5,
            fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
        )
    )

    x_start = _as_float(x_bins[0]) if x_bins else None
    x_end = _as_float(x_bins[-1]) if x_bins else None
    y_start = _as_float(y_bins[0]) if y_bins else None
    y_end = _as_float(y_bins[-1]) if y_bins else None
    if x_start is not None and x_end is not None:
        drawing.add(
            String(
                plot_x0,
                plot_y0 - 10,
                f"{x_start:.0f}",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                plot_x0 + plot_w - 12,
                plot_y0 - 10,
                f"{x_end:.0f}",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
    if y_start is not None and y_end is not None:
        drawing.add(
            String(
                plot_x0 - 24,
                plot_y0,
                f"{y_start:.0f}",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                plot_x0 - 26,
                plot_y0 + plot_h - 2,
                f"{y_end:.0f}",
                fontSize=6,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
    return drawing
