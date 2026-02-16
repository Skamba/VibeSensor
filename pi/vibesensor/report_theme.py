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
    # Card tone backgrounds
    "card_neutral_bg": "#f4f7fb",
    "card_success_bg": "#e7f5ee",
    "card_warn_bg": "#fef3e0",
    "card_error_bg": "#fce8e6",
    # Card tone borders
    "card_neutral_border": "#cad5e4",
    "card_success_border": "#a8dab5",
    "card_warn_border": "#f5c98a",
    "card_error_border": "#f5a6a2",
    # Confidence pill backgrounds
    "pill_high_bg": "#e7f5ee",
    "pill_high_text": "#0d7a45",
    "pill_medium_bg": "#fef3e0",
    "pill_medium_text": "#8a4500",
    "pill_low_bg": "#f4f7fb",
    "pill_low_text": "#4f5d73",
    # Zebra striping
    "table_zebra_bg": "#f8fafc",
}

REPORT_SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18}
REPORT_RADIUS = {"sm": 6, "md": 10}

# Card layout constants (points).
CARD_PADDING = 10
CARD_RADIUS = 8

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

# Heat-map endpoint colors for the car diagram.
HEAT_LOW = "#2ca25f"   # green (low vibration)
HEAT_MID = "#f0cf4a"   # yellow
HEAT_HIGH = "#d73027"  # red (high vibration)
