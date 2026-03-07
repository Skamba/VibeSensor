"""PDF report car location diagram compatibility facade."""

from __future__ import annotations

from .pdf_diagram_layout import (
    _build_sensor_render_plan,
    _estimate_text_width,
    _resolve_marker_states,
)
from .pdf_diagram_models import LabelRenderPlan, MarkerRenderPlan, MarkerState
from .pdf_diagram_render import car_location_diagram

__all__ = [
    "LabelRenderPlan",
    "MarkerRenderPlan",
    "MarkerState",
    "_build_sensor_render_plan",
    "_estimate_text_width",
    "_resolve_marker_states",
    "car_location_diagram",
]
