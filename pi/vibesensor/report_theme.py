from __future__ import annotations

# Material Design 3 inspired roles used by PDF report rendering.
REPORT_COLORS = {
    "ink": "#152131",
    "muted": "#4f5d73",
    "border": "#cad5e4",
    "surface": "#f4f7fb",
    "surface_alt": "#e8eef6",
    "primary": "#0b57d0",
    "success": "#0f9d58",
    "warning": "#b35d00",
    "danger": "#c5221f",
    "axis": "#7b8da0",
    "table_header_bg": "#e8eef5",
    "table_header_border": "#b9c7d5",
    "table_row_border": "#d6dee8",
    "table_box": "#c8d3df",
    "text_primary": "#1f3a52",
    "text_secondary": "#4f5d73",
    "text_muted": "#5a6778",
}

REPORT_SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18}
REPORT_RADIUS = {"sm": 6, "md": 10}

# Shared plot accents (aligned with ui/src/theme.ts palette intent).
REPORT_PLOT_COLORS = {
    "vibration": "#0b57d0",
    "dominant_freq": "#9334e6",
    "amplitude_speed": "#ef6c00",
    "matched_series": ["#0b57d0", "#0f9d58", "#9334e6", "#ef6c00"],
    "predicted_curve": "#4f5d73",
}

FINDING_SOURCE_COLORS = {
    "wheel/tire": "#0f9d58",
    "driveline": "#0b57d0",
    "engine": "#c5221f",
    "unknown": "#4f5d73",
}
