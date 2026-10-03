"""Focused test-support helpers for server tests.

Import shared synthetic-data builders and assertions from ``test_support``.
This package is the canonical shared test-helper entrypoint.
"""

from typing import Any

from test_support.analysis import extract_top, run_analysis, top_confidence
from test_support.assertions import (
    assert_confidence_level_valid,
    assert_no_wheel_fault,
    assert_strongest_location,
    assert_wheel_source,
    parse_speed_band,
)
from test_support.core import (
    ALL_SENSORS,
    ALL_WHEEL_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RL,
    SENSOR_RR,
    SPEED_HIGH,
    SPEED_LOW,
    SPEED_MID,
    _stable_hash,
    assert_summary_sections,
    assert_top_cause_contract,
    engine_hz,
    standard_metadata,
    wheel_hz,
)
from test_support.fault_scenarios import (
    build_speed_sweep_fault_samples,
    make_engine_order_samples,
    make_fault_samples,
    make_speed_sweep_fault_samples,
)
from test_support.pdf import extract_pdf_text
from test_support.polling import async_wait_until, wait_until
from test_support.sample_scenarios import (
    make_idle_samples,
    make_noise_samples,
    make_ramp_samples,
    make_sample,
    make_transient_samples,
)

__all__ = [
    # analysis
    "extract_top",
    "run_analysis",
    "top_confidence",
    # assertions
    "assert_confidence_level_valid",
    "assert_no_wheel_fault",
    "assert_strongest_location",
    "assert_wheel_source",
    "parse_speed_band",
    # core
    "ALL_SENSORS",
    "ALL_WHEEL_SENSORS",
    "SENSOR_FL",
    "SENSOR_FR",
    "SENSOR_RL",
    "SENSOR_RR",
    "SPEED_HIGH",
    "SPEED_LOW",
    "SPEED_MID",
    "_stable_hash",
    "assert_summary_sections",
    "assert_top_cause_contract",
    "engine_hz",
    "extract_pdf_text",
    "async_wait_until",
    "wait_until",
    "standard_metadata",
    "wheel_hz",
    # fault_scenarios
    "build_speed_sweep_fault_samples",
    "make_engine_order_samples",
    "make_fault_samples",
    "make_speed_sweep_fault_samples",
    # sample_scenarios
    "make_idle_samples",
    "make_noise_samples",
    "make_ramp_samples",
    "make_sample",
    "make_transient_samples",
    # local
    "response_payload",
]


def response_payload(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    return response
