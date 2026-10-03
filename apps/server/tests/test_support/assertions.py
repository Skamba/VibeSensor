"""Reusable diagnosis assertions for synthetic-analysis tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from test_support.analysis import extract_top
from vibesensor.summary.finding_fields import finding_from_payload


def _cause_source(cause: dict[str, Any]) -> str:
    """Get the normalized source from a top-cause or finding dict."""
    return finding_from_payload(cause).source_normalized


def _cause_confidence(cause: dict[str, Any]) -> float:
    return float(cause.get("confidence", 0))


def _assert_summary_contract(summary: dict[str, Any], msg: str = "") -> None:
    assert isinstance(summary.get("findings"), list), f"Missing or invalid findings list. {msg}"
    assert isinstance(summary.get("top_causes"), list), f"Missing or invalid top_causes list. {msg}"
    assert isinstance(summary.get("run_suitability"), list), (
        f"Missing or invalid run_suitability list. {msg}"
    )
    assert "most_likely_origin" in summary, f"Missing most_likely_origin section. {msg}"


def _top_causes(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return summary.get("top_causes") or []


def _top_cause_or_fail(summary: dict[str, Any], msg: str = "") -> dict[str, Any]:
    _assert_summary_contract(summary, msg)
    top = extract_top(summary)
    assert top is not None, f"No top cause found. {msg}"
    assert "suspected_source" in top, f"Top cause missing suspected_source. {msg}"
    assert "confidence" in top, f"Top cause missing confidence. {msg}"
    return top


def _iter_causes_at_or_above(
    summary: dict[str, Any],
    confidence_threshold: float,
) -> Iterator[tuple[dict[str, Any], float]]:
    for cause in _top_causes(summary):
        confidence = _cause_confidence(cause)
        if confidence >= confidence_threshold:
            yield cause, confidence


def assert_no_wheel_fault(summary: dict[str, Any], msg: str = "") -> None:
    """Assert no wheel/tire fault is diagnosed with medium+ confidence.

    Low-confidence matches (< 0.40) are tolerated because broadband noise
    can accidentally align with wheel-order frequencies at certain speeds.
    """
    _assert_summary_contract(summary, msg)
    for c, conf in _iter_causes_at_or_above(summary, 0.40):
        src = _cause_source(c)
        if "wheel" in src:
            loc = c.get("strongest_location") or c.get("location_hotspot", "")
            raise AssertionError(f"Unexpected wheel fault: {src} @ {loc} conf={conf:.2f}. {msg}")


# ---------------------------------------------------------------------------
# Additional assertion helpers
# ---------------------------------------------------------------------------


def assert_wheel_source(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the top cause identifies a wheel/tire source."""
    src = _cause_source(_top_cause_or_fail(summary, msg))
    assert "wheel" in src or "tire" in src, f"Expected wheel/tire source, got '{src}'. {msg}"


def assert_strongest_location(summary: dict[str, Any], expected_sensor: str, msg: str = "") -> None:
    """Assert the top cause's strongest_location matches *expected_sensor*."""
    top = _top_cause_or_fail(summary, msg)
    loc = (top.get("strongest_location") or "").lower()
    assert loc == expected_sensor.lower(), (
        f"Expected strongest_location='{expected_sensor}', got '{loc}'. {msg}"
    )


# ---------------------------------------------------------------------------
# Strict and tolerant no-fault helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Speed band and warnings assertion helpers
# ---------------------------------------------------------------------------


def assert_confidence_level_valid(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the top cause carries one of the three action-defined confidence levels."""
    top = _top_cause_or_fail(summary, msg)
    level = top.get("confidence_level")
    assert level in ("strong", "moderate", "weak"), f"Bad confidence_level: {level}. {msg}"


# ---------------------------------------------------------------------------
# Pairwise monotonic check
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Composite diagnosis contract assertion
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Forbidden / allowed system assertion helpers (for negative testing)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Weird-sensor-mix assertion helpers
# ---------------------------------------------------------------------------


def parse_speed_band(finding: dict[str, Any]) -> tuple[float, float]:
    """Parse ``strongest_speed_band`` like ``'60-80 km/h'`` into ``(60.0, 80.0)``."""
    speed_band = str(finding.get("strongest_speed_band") or "")
    parts = speed_band.replace("km/h", "").strip().split("-")
    try:
        low = float(parts[0].strip())
        high = float(parts[-1].strip()) if len(parts) > 1 else low
    except (ValueError, IndexError):
        low = high = 0.0
    return low, high
