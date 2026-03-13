"""Core metadata, vehicle-profile, frequency helpers, and polling utilities for tests."""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import time
from collections.abc import Callable
from functools import cache
from io import BytesIO
from typing import Any

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)

TIRE_CIRC = tire_circumference_m_from_spec(
    DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
    DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
    DEFAULT_ANALYSIS_SETTINGS["rim_in"],
    deflection_factor=DEFAULT_ANALYSIS_SETTINGS.get("tire_deflection_factor"),
)
FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]

# Canonical sensor names / corners
SENSOR_FL = "front-left"
SENSOR_FR = "front-right"
SENSOR_RL = "rear-left"
SENSOR_RR = "rear-right"
ALL_WHEEL_SENSORS = [SENSOR_FL, SENSOR_FR, SENSOR_RL, SENSOR_RR]
ALL_SENSORS = ALL_WHEEL_SENSORS  # convenience alias

# Non-wheel sensor names for multi-sensor scenarios
SENSOR_ENGINE = "engine-bay"
SENSOR_DRIVESHAFT = "driveshaft-tunnel"
SENSOR_TRANSMISSION = "transmission"
SENSOR_TRUNK = "trunk"
SENSOR_DRIVER_SEAT = "driver-seat"
SENSOR_FRONT_SUBFRAME = "front-subframe"
SENSOR_REAR_SUBFRAME = "rear-subframe"
SENSOR_PASSENGER_SEAT = "front-passenger-seat"

NON_WHEEL_SENSORS = [
    SENSOR_ENGINE,
    SENSOR_DRIVESHAFT,
    SENSOR_TRANSMISSION,
    SENSOR_TRUNK,
    SENSOR_DRIVER_SEAT,
    SENSOR_FRONT_SUBFRAME,
    SENSOR_REAR_SUBFRAME,
    SENSOR_PASSENGER_SEAT,
]

# Corner code → canonical sensor name
CORNER_SENSORS = {
    "FL": SENSOR_FL,
    "FR": SENSOR_FR,
    "RL": SENSOR_RL,
    "RR": SENSOR_RR,
}

# Speed bands
SPEED_LOW = 50.0  # km/h  (wheel_1x ≈ 6.5 Hz with default tires, above MIN_ANALYSIS_FREQ_HZ)
SPEED_MID = 60.0
SPEED_HIGH = 100.0
SPEED_VERY_HIGH = 120.0

# ---------------------------------------------------------------------------
# Car profiles – five realistic vehicle configurations for cross-profile
# parameterised testing.  Each profile overrides tire geometry and drivetrain
# ratios that affect wheel/engine frequency calculations.
# ---------------------------------------------------------------------------

CAR_PROFILES: list[dict[str, Any]] = [
    {
        "name": "performance_suv",
        "tire_width_mm": 285.0,
        "tire_aspect_pct": 30.0,
        "rim_in": 21.0,
        "final_drive_ratio": 3.08,
        "current_gear_ratio": 0.64,
    },
    {
        "name": "economy_sedan",
        "tire_width_mm": 205.0,
        "tire_aspect_pct": 55.0,
        "rim_in": 16.0,
        "final_drive_ratio": 3.94,
        "current_gear_ratio": 0.73,
    },
    {
        "name": "sports_coupe",
        "tire_width_mm": 225.0,
        "tire_aspect_pct": 40.0,
        "rim_in": 18.0,
        "final_drive_ratio": 3.27,
        "current_gear_ratio": 0.85,
    },
    {
        "name": "off_road_truck",
        "tire_width_mm": 265.0,
        "tire_aspect_pct": 70.0,
        "rim_in": 17.0,
        "final_drive_ratio": 3.73,
        "current_gear_ratio": 0.75,
    },
    {
        "name": "compact_city",
        "tire_width_mm": 195.0,
        "tire_aspect_pct": 65.0,
        "rim_in": 15.0,
        "final_drive_ratio": 4.06,
        "current_gear_ratio": 0.68,
    },
]

CAR_PROFILE_IDS: list[str] = [p["name"] for p in CAR_PROFILES]


def _normalize_wheel_slot(name: str) -> str | None:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    aliases = {
        "fl": SENSOR_FL,
        "fr": SENSOR_FR,
        "rl": SENSOR_RL,
        "rr": SENSOR_RR,
    }
    if normalized in aliases:
        return aliases[normalized]
    axle = "front" if "front" in normalized else "rear" if "rear" in normalized else None
    side = "left" if "left" in normalized else "right" if "right" in normalized else None
    if axle and side:
        return f"{axle}-{side}"
    return None


def _corner_transfer_fraction(fault_sensor: str, sink_sensor: str) -> float:
    """Deterministic transfer fraction for structure-borne coupling."""
    fault = _normalize_wheel_slot(fault_sensor)
    sink = _normalize_wheel_slot(sink_sensor)
    # Non-corner sensors still pick up cabin/chassis energy.
    if fault is None or sink is None:
        return 0.32
    if fault == sink:
        return 1.0
    fault_axle, fault_side = fault.split("-", maxsplit=1)
    sink_axle, sink_side = sink.split("-", maxsplit=1)
    if fault_side == sink_side and fault_axle != sink_axle:
        return 0.52
    if fault_axle == sink_axle and fault_side != sink_side:
        return 0.48
    return 0.40


def _fault_transfer_fraction(
    fault_sensor: str,
    sink_sensor: str,
    *,
    override: float | None,
) -> float:
    if sink_sensor == fault_sensor:
        return 1.0
    if override is not None:
        return max(0.0, min(1.0, override))
    # Keep realistic coupling while preserving clear localization headroom.
    return _corner_transfer_fraction(fault_sensor, sink_sensor) * 0.58


@cache
def _profile_circ_cached(
    tire_width_mm: int,
    tire_aspect_pct: int,
    rim_in: int,
    tire_deflection_factor: float | None,
) -> float:
    circ = tire_circumference_m_from_spec(
        tire_width_mm,
        tire_aspect_pct,
        rim_in,
        deflection_factor=tire_deflection_factor,
    )
    assert circ is not None and circ > 0
    return circ


def profile_circ(profile: dict[str, Any]) -> float:
    """Compute tire circumference for a car profile."""
    return _profile_circ_cached(
        profile["tire_width_mm"],
        profile["tire_aspect_pct"],
        profile["rim_in"],
        profile.get("tire_deflection_factor"),
    )


def profile_wheel_hz(profile: dict[str, Any], speed_kmh: float) -> float:
    """Compute wheel-1x Hz for a car profile at *speed_kmh*."""
    circ = profile_circ(profile)
    hz = wheel_hz_from_speed_kmh(speed_kmh, circ)
    assert hz is not None and hz > 0
    return hz


@cache
def _profile_metadata_base(
    tire_width_mm: int,
    tire_aspect_pct: int,
    rim_in: int,
    tire_deflection_factor: float | None,
    final_drive_ratio: float,
    current_gear_ratio: float,
) -> tuple[tuple[str, Any], ...]:
    return tuple(
        standard_metadata(
            tire_circumference_m=_profile_circ_cached(
                tire_width_mm,
                tire_aspect_pct,
                rim_in,
                tire_deflection_factor,
            ),
            final_drive_ratio=final_drive_ratio,
            current_gear_ratio=current_gear_ratio,
        ).items(),
    )


def profile_metadata(profile: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build run metadata for a specific car profile."""
    meta = dict(
        _profile_metadata_base(
            profile["tire_width_mm"],
            profile["tire_aspect_pct"],
            profile["rim_in"],
            profile.get("tire_deflection_factor"),
            profile["final_drive_ratio"],
            profile["current_gear_ratio"],
        ),
    )
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Stable deterministic hash (replaces Python hash() which varies per process)
# ---------------------------------------------------------------------------


@cache
def _stable_hash(s: str) -> int:
    """Return a stable positive integer derived from *s* (deterministic across runs)."""
    return int(hashlib.md5(s.encode()).hexdigest(), 16)


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def standard_metadata(*, language: str = "en", **overrides: Any) -> dict[str, Any]:
    """Return a minimal valid run-metadata dict."""
    meta: dict[str, Any] = {
        "tire_circumference_m": TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": FINAL_DRIVE,
        "current_gear_ratio": GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
        "language": language,
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# Frequency helpers
# ---------------------------------------------------------------------------


def wheel_hz(speed_kmh: float) -> float:
    """Compute wheel-1x frequency for *speed_kmh*."""
    hz = wheel_hz_from_speed_kmh(speed_kmh, TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def engine_hz(
    speed_kmh: float,
    gear_ratio: float = GEAR_RATIO,
    final_drive: float = FINAL_DRIVE,
) -> float:
    """Rough engine-1x Hz from speed (2-stroke assumption for simplicity)."""
    whz = wheel_hz(speed_kmh)
    return whz * final_drive * gear_ratio


# ---------------------------------------------------------------------------
# Polling helpers
# ---------------------------------------------------------------------------


def wait_until(
    predicate: Callable[[], object], timeout_s: float = 2.0, step_s: float = 0.02
) -> bool:
    """Poll *predicate* until it returns truthy, or *timeout_s* expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return False


async def async_wait_until(
    predicate: Callable[[], object], timeout_s: float = 2.0, step_s: float = 0.02
) -> bool:
    """Async version of :func:`wait_until` — yields to the event loop between polls."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(step_s)
    return False


# ---------------------------------------------------------------------------
# PDF text extraction helper
# ---------------------------------------------------------------------------


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF byte string using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


# ---------------------------------------------------------------------------
# Diagnosis contract assertion helpers
# ---------------------------------------------------------------------------

_FINDING_REQUIRED_FIELDS = (
    "finding_id",
    "suspected_source",
    "confidence",
    "evidence_summary",
    "frequency_hz_or_order",
)

_TOP_CAUSE_REQUIRED_FIELDS = (
    "finding_id",
    "suspected_source",
    "confidence",
    "strongest_location",
    "strongest_speed_band",
)


def _assert_confidence_valid(
    d: dict[str, Any],
    field: str,
    confidence_range: tuple[float, float],
) -> None:
    """Assert *field* in *d* is a finite number within *confidence_range*."""
    conf = d.get(field, 0.0)
    assert isinstance(conf, (int, float)), f"{field} is not numeric: {conf!r}"
    assert not math.isnan(conf), f"{field} is NaN"
    lo, hi = confidence_range
    assert lo <= conf <= hi, f"{field} {conf:.3f} not in [{lo:.2f}, {hi:.2f}]"


def _assert_source_contains(
    d: dict[str, Any],
    field: str,
    expected: str,
) -> None:
    """Assert *field* in *d* contains *expected* (case-insensitive)."""
    source = str(d.get(field, "")).lower()
    assert expected.lower() in source, f"Expected source containing {expected!r}, got {source!r}"


def _assert_location_contains(d: dict[str, Any], expected: str) -> None:
    """Assert ``strongest_location`` in *d* contains *expected* (case-insensitive)."""
    loc = str(d.get("strongest_location") or "").lower()
    assert expected.lower() in loc, f"Expected location containing {expected!r}, got {loc!r}"


def _assert_speed_band_overlap(band: str, min_kmh: float, max_kmh: float) -> None:
    """Assert a speed-band string overlaps the given range."""
    assert band and "km/h" in band, f"No valid speed band found: {band!r}"
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", band.replace("km/h", "").strip())
    assert m, f"Cannot parse speed band: {band!r}"
    low, high = float(m.group(1)), float(m.group(2))
    assert high > min_kmh and low < max_kmh, (
        f"Speed band {band} ({low}-{high}) does not overlap expected range {min_kmh}-{max_kmh} km/h"
    )


def assert_finding_contract(
    finding: dict[str, Any],
    *,
    required_fields: tuple[str, ...] = _FINDING_REQUIRED_FIELDS,
    expected_source: str | None = None,
    expected_location: str | None = None,
    expected_speed_band_range: tuple[float, float] | None = None,
    confidence_range: tuple[float, float] = (0.0, 1.0),
    expected_finding_key: str | None = None,
    expect_no_weak_spatial: bool = False,
) -> None:
    """Validate a single finding dict satisfies the diagnosis contract."""
    for field_name in required_fields:
        assert field_name in finding, (
            f"Missing required field '{field_name}' in finding: {list(finding.keys())}"
        )

    _assert_confidence_valid(finding, "confidence", confidence_range)

    if expected_source is not None:
        _assert_source_contains(finding, "suspected_source", expected_source)

    if expected_location is not None:
        _assert_location_contains(finding, expected_location)

    if expected_speed_band_range is not None:
        band = str(finding.get("strongest_speed_band") or "")
        _assert_speed_band_overlap(band, *expected_speed_band_range)

    if expected_finding_key is not None:
        assert finding.get("finding_key") == expected_finding_key, (
            f"Expected finding_key={expected_finding_key!r}, got {finding.get('finding_key')!r}"
        )

    if expect_no_weak_spatial:
        assert not finding.get("weak_spatial_separation", True), (
            "Expected strong spatial separation but got weak"
        )


def assert_top_cause_contract(
    top_cause: dict[str, Any],
    *,
    required_fields: tuple[str, ...] = _TOP_CAUSE_REQUIRED_FIELDS,
    expected_source: str | None = None,
    expected_location: str | None = None,
    expected_speed_band_range: tuple[float, float] | None = None,
    confidence_range: tuple[float, float] = (0.0, 1.0),
    expect_no_weak_spatial: bool = False,
    expect_wheel_signatures: bool = False,
    expect_not_engine: bool = False,
) -> None:
    """Validate a top_cause dict satisfies the contract."""
    for field_name in required_fields:
        assert field_name in top_cause, (
            f"Missing required field '{field_name}' in top_cause: {list(top_cause.keys())}"
        )

    _assert_confidence_valid(top_cause, "confidence", confidence_range)

    if expected_source is not None:
        _assert_source_contains(top_cause, "suspected_source", expected_source)

    if expected_location is not None:
        _assert_location_contains(top_cause, expected_location)

    if expected_speed_band_range is not None:
        band = str(top_cause.get("strongest_speed_band") or "")
        _assert_speed_band_overlap(band, *expected_speed_band_range)

    if expect_no_weak_spatial:
        assert not top_cause.get("weak_spatial_separation", True), (
            "Expected strong spatial separation but got weak"
        )

    if expect_wheel_signatures:
        sigs = top_cause.get("signatures_observed", [])
        sig_text = " ".join(str(s).lower() for s in sigs)
        assert "wheel" in sig_text or "wiel" in sig_text, (
            f"Expected wheel/wiel signatures, got {sigs!r}"
        )

    if expect_not_engine:
        source = str(top_cause.get("source", "")).lower()
        assert "engine" not in source, f"Source should not be engine, got {source!r}"
        assert "driveline" not in source, f"Source should not be driveline, got {source!r}"


def assert_summary_sections(
    summary: dict[str, Any],
    *,
    expected_lang: str | None = None,
    required_sections: tuple[str, ...] = (
        "findings",
        "top_causes",
        "most_likely_origin",
        "test_plan",
        "phase_info",
        "run_suitability",
    ),
    min_findings: int = 0,
    min_top_causes: int = 0,
) -> None:
    """Validate the full summary dict has all required diagnosis sections."""
    for sec in required_sections:
        assert sec in summary, f"Missing required section '{sec}' in summary"

    if expected_lang is not None:
        assert summary.get("lang") == expected_lang, (
            f"Expected lang={expected_lang!r}, got {summary.get('lang')!r}"
        )

    findings = summary.get("findings", [])
    assert len(findings) >= min_findings, (
        f"Expected >= {min_findings} findings, got {len(findings)}"
    )

    top_causes = summary.get("top_causes", [])
    assert len(top_causes) >= min_top_causes, (
        f"Expected >= {min_top_causes} top_causes, got {len(top_causes)}"
    )
