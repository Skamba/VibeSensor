"""Compatibility facade for scenario-oriented test helpers."""

from __future__ import annotations

from .fault_scenarios import (
    make_dual_fault_samples,
    make_engine_order_samples,
    make_fault_samples,
    make_gain_mismatch_samples,
    make_profile_dual_fault_samples,
    make_profile_engine_order_samples,
    make_profile_fault_samples,
    make_profile_gain_mismatch_samples,
    make_profile_speed_sweep_fault_samples,
    make_speed_sweep_fault_samples,
)
from .perturbation_scenarios import (
    make_clipped_samples,
    make_clock_skew_samples,
    make_dropout_samples,
    make_out_of_order_samples,
    make_speed_jitter_samples,
)
from .sample_scenarios import (
    make_diffuse_samples,
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_road_phase_samples,
    make_sample,
    make_transient_samples,
)

__all__ = [
    "make_clipped_samples",
    "make_clock_skew_samples",
    "make_diffuse_samples",
    "make_dropout_samples",
    "make_dual_fault_samples",
    "make_engine_order_samples",
    "make_fault_samples",
    "make_gain_mismatch_samples",
    "make_idle_samples",
    "make_noise_samples",
    "make_out_of_order_samples",
    "make_profile_dual_fault_samples",
    "make_profile_engine_order_samples",
    "make_profile_fault_samples",
    "make_profile_gain_mismatch_samples",
    "make_profile_speed_sweep_fault_samples",
    "make_ramp_samples",
    "make_road_phase_samples",
    "make_sample",
    "make_speed_jitter_samples",
    "make_speed_sweep_fault_samples",
    "make_transient_samples",
]
