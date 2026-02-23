from __future__ import annotations

# Aligned with apps/ui/src/styles/app.css design tokens (purple accent, print-friendly light).
REPORT_COLORS = {
    "ink": "#1a1c24",
    "muted": "#52555e",
    "border": "#c4c7d0",
    "surface": "#f8f9fb",
    "surface_alt": "#f1f2f6",
    "primary": "#7c3aed",
    "success": "#0f9d58",
    "warning": "#b35d00",
    "danger": "#c5221f",
    "axis": "#7b8da0",
    "table_header_bg": "#f1f2f6",
    "table_header_border": "#c4c7d0",
    "table_row_border": "#dcdfe6",
    "table_box": "#c4c7d0",
    "text_primary": "#1a1c24",
    "text_secondary": "#52555e",
    "text_muted": "#6b6e78",
    # Card tone backgrounds
    "card_neutral_bg": "#f8f9fb",
    "card_success_bg": "#e7f5ee",
    "card_warn_bg": "#fef3e0",
    "card_error_bg": "#fce8e6",
    # Card tone borders
    "card_neutral_border": "#c4c7d0",
    "card_success_border": "#a8dab5",
    "card_warn_border": "#f5c98a",
    "card_error_border": "#f5a6a2",
    # Confidence pill backgrounds
    "pill_high_bg": "#e7f5ee",
    "pill_high_text": "#0d7a45",
    "pill_medium_bg": "#fef3e0",
    "pill_medium_text": "#8a4500",
    "pill_low_bg": "#f1f2f6",
    "pill_low_text": "#52555e",
    # Zebra striping
    "table_zebra_bg": "#fafafc",
}

FINDING_SOURCE_COLORS = {
    "wheel/tire": "#0f9d58",
    "driveline": "#7c3aed",
    "engine": "#c5221f",
    "unknown": "#52555e",
}

# Heat-map endpoint colors for the car diagram.
HEAT_LOW = "#2ca25f"  # green (low vibration)
HEAT_MID = "#f0cf4a"  # yellow
HEAT_HIGH = "#d73027"  # red (high vibration)
