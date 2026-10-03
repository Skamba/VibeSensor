"""Stable facade for fault-oriented synthetic scenario builders."""

from __future__ import annotations

from test_support.engine_fault_scenarios import make_engine_order_samples
from test_support.wheel_fault_scenarios import (
    build_speed_sweep_fault_samples,
    make_fault_samples,
    make_speed_sweep_fault_samples,
)

__all__ = [
    "build_speed_sweep_fault_samples",
    "make_engine_order_samples",
    "make_fault_samples",
    "make_speed_sweep_fault_samples",
]
