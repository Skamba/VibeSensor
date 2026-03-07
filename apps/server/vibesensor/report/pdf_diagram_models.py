"""Typed render plans for the car location diagram."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MarkerState = Literal["connected-active", "connected-inactive", "disconnected"]


@dataclass(frozen=True)
class MarkerRenderPlan:
    """Computed render parameters for a single location marker."""

    name: str
    x: float
    y: float
    state: MarkerState
    fill: str
    stroke: str
    stroke_width: float
    radius: float


@dataclass(frozen=True)
class LabelRenderPlan:
    """Computed render parameters for a location label."""

    name: str
    text: str
    x: float
    y: float
    anchor: str
    color: str
    font_size: float
    bbox: tuple[float, float, float, float]
