"""Reusable diagnosis assertions for synthetic-analysis tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vibesensor.domain import Finding

from .analysis import extract_top, top_confidence, top_corner_label

_CORNER_LABEL_TOKENS: dict[str, tuple[str, ...]] = {
    "FL": ("front left", "front-left", "fl"),
    "FR": ("front right", "front-right", "fr"),
    "RL": ("rear left", "rear-left", "rl"),
    "RR": ("rear right", "rear-right", "rr"),
}


def _corner_in_label(label: str | None, corner: str) -> bool:
    """Check if a corner code (FL/FR/RL/RR) or location matches the label."""
    if not label:
        return False
    label_lower = label.lower()
    tokens = _CORNER_LABEL_TOKENS.get(corner.upper(), ())
    return any(t in label_lower for t in tokens)


def assert_corner_detected(summary: dict[str, Any], expected_corner: str, msg: str = "") -> None:
    """Assert the top cause points to *expected_corner* (FL/FR/RL/RR)."""
    label = top_corner_label(summary)
    assert label is not None, f"No top cause found. {msg}"
    assert _corner_in_label(label, expected_corner), (
        f"Expected corner {expected_corner} in '{label}'. {msg}"
    )


def _cause_source(cause: dict[str, Any]) -> str:
    """Get the normalized source from a top-cause or finding dict."""
    return Finding.from_payload(cause).source_normalized


def _cause_confidence(cause: dict[str, Any]) -> float:
    return float(cause.get("confidence", 0))


def _top_causes(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return summary.get("top_causes") or []


def _top_cause_or_fail(summary: dict[str, Any], msg: str = "") -> dict[str, Any]:
    top = extract_top(summary)
    assert top is not None, f"No top cause found. {msg}"
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


def assert_source_is(summary: dict[str, Any], expected: str, msg: str = "") -> None:
    """Assert the top cause's source contains *expected* (case-insensitive)."""
    src = _cause_source(_top_cause_or_fail(summary, msg))
    assert expected.lower() in src, f"Expected '{expected}' in source, got '{src}'. {msg}"


def assert_confidence_between(summary: dict[str, Any], lo: float, hi: float, msg: str = "") -> None:
    """Assert top cause confidence is within [lo, hi]."""
    conf = top_confidence(summary)
    assert lo <= conf <= hi, f"Confidence {conf:.3f} not in [{lo}, {hi}]. {msg}"


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


def assert_strict_no_fault(summary: dict[str, Any], msg: str = "") -> None:
    """Assert clean baseline: no causes at all, or all confidence < 0.10.

    Use for known-clean scenarios (pure noise, idle-only, etc.).
    """
    for c in _top_causes(summary):
        conf = _cause_confidence(c)
        src = _cause_source(c)
        assert conf < 0.10, f"Strict no-fault violated: {src} conf={conf:.3f}. {msg}"


def assert_tolerant_no_fault(summary: dict[str, Any], msg: str = "") -> None:
    """Assert ambiguous/diffuse/transient-heavy case: no HIGH-confidence wheel fault.

    Allows low-confidence findings (< 0.50) since diffuse noise or transients
    can produce incidental matches.
    """
    for c, conf in _iter_causes_at_or_above(summary, 0.50):
        src = _cause_source(c)
        if "wheel" in src:
            loc = c.get("strongest_location") or ""
            raise AssertionError(
                f"Tolerant no-fault violated: {src} @ {loc} conf={conf:.2f}. {msg}",
            )


# ---------------------------------------------------------------------------
# Speed band and warnings assertion helpers
# ---------------------------------------------------------------------------


def assert_speed_band_present(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the top cause has a strongest_speed_band field."""
    top = _top_cause_or_fail(summary, msg)
    band = top.get("strongest_speed_band")
    assert band is not None and band != "", f"Missing strongest_speed_band in top cause. {msg}"


def assert_has_warnings(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the summary has a 'warnings' field (may be empty list)."""
    assert "warnings" in summary, f"Missing 'warnings' field. {msg}"
    assert isinstance(summary["warnings"], list), f"'warnings' is not a list. {msg}"


def assert_confidence_label_valid(summary: dict[str, Any], msg: str = "") -> None:
    """Assert the top cause has a valid confidence label key and tone."""
    top = _top_cause_or_fail(summary, msg)
    label = top.get("confidence_label_key")
    assert label in ("CONFIDENCE_HIGH", "CONFIDENCE_MEDIUM", "CONFIDENCE_LOW"), (
        f"Bad confidence_label_key: {label}. {msg}"
    )
    tone = top.get("confidence_tone")
    assert tone in ("success", "warn", "neutral"), f"Bad confidence_tone: {tone}. {msg}"


# ---------------------------------------------------------------------------
# Pairwise monotonic check
# ---------------------------------------------------------------------------


def assert_pairwise_monotonic(
    values: list[float],
    *,
    tolerance: float = 0.05,
    labels: list[str] | None = None,
    msg: str = "",
) -> None:
    """Assert pairwise non-decreasing trend (with tolerance for small regressions).

    Each adjacent pair must satisfy: values[i+1] >= values[i] - tolerance.
    """
    for i in range(len(values) - 1):
        a, b = values[i], values[i + 1]
        a_label = labels[i] if labels else str(i)
        b_label = labels[i + 1] if labels else str(i + 1)
        assert b >= a - tolerance, (
            f"Pairwise monotonic violated at [{a_label}]→[{b_label}]: "
            f"{a:.4f} → {b:.4f} (tolerance={tolerance}). {msg}"
        )


# ---------------------------------------------------------------------------
# Composite diagnosis contract assertion
# ---------------------------------------------------------------------------


def assert_diagnosis_contract(
    summary: dict[str, Any],
    *,
    expected_source: str | None = None,
    expected_sensor: str | None = None,
    expected_corner: str | None = None,
    min_confidence: float = 0.15,
    max_confidence: float = 1.0,
    msg: str = "",
) -> None:
    """Composite assertion validating the normalized diagnosis contract.

    Checks: source classification, inferred location, confidence range,
    confidence label, speed band, and warnings presence.
    """
    top = _top_cause_or_fail(summary, msg)

    # Source classification
    if expected_source:
        src = _cause_source(top)
        assert expected_source.lower() in src, (
            f"Expected source '{expected_source}' in '{src}'. {msg}"
        )

    # Location
    if expected_sensor:
        assert_strongest_location(summary, expected_sensor, msg=msg)
    if expected_corner:
        assert_corner_detected(summary, expected_corner, msg=msg)

    # Confidence range
    assert_confidence_between(summary, min_confidence, max_confidence, msg=msg)

    # Confidence label and tone
    assert_confidence_label_valid(summary, msg=msg)

    # Speed band
    assert_speed_band_present(summary, msg=msg)

    # Warnings list
    assert_has_warnings(summary, msg=msg)


# ---------------------------------------------------------------------------
# Forbidden / allowed system assertion helpers (for negative testing)
# ---------------------------------------------------------------------------


def assert_forbidden_systems(
    summary: dict[str, Any],
    forbidden: list[str],
    *,
    confidence_threshold: float = 0.40,
    msg: str = "",
) -> None:
    """Assert that none of the *forbidden* source keywords appear at or above threshold.

    Each entry in *forbidden* is matched case-insensitively against the source
    field of every top-cause.
    """
    for c, conf in _iter_causes_at_or_above(summary, confidence_threshold):
        src = _cause_source(c)
        for keyword in forbidden:
            if keyword.lower() in src:
                loc = c.get("strongest_location") or ""
                raise AssertionError(
                    f"Forbidden system '{keyword}' found: {src} @ {loc} "
                    f"conf={conf:.3f} (threshold={confidence_threshold}). {msg}",
                )


def assert_only_allowed_systems(
    summary: dict[str, Any],
    allowed: list[str],
    *,
    confidence_threshold: float = 0.40,
    msg: str = "",
) -> None:
    """Assert that ONLY sources matching *allowed* keywords appear at or above threshold.

    Any source at/above threshold that does not match any allowed keyword triggers
    a failure.
    """
    for c, conf in _iter_causes_at_or_above(summary, confidence_threshold):
        src = _cause_source(c)
        if not any(kw.lower() in src for kw in allowed):
            loc = c.get("strongest_location") or ""
            raise AssertionError(
                f"Unexpected system '{src}' @ {loc} conf={conf:.3f} "
                f"(allowed={allowed}, threshold={confidence_threshold}). {msg}",
            )


def assert_no_persistent_fault(
    summary: dict[str, Any],
    *,
    confidence_threshold: float = 0.40,
    msg: str = "",
) -> None:
    """Assert no source is diagnosed as a persistent fault above threshold.

    Use for transient-only and no-fault scenarios.
    """
    for c, conf in _iter_causes_at_or_above(summary, confidence_threshold):
        src = _cause_source(c)
        loc = c.get("strongest_location") or ""
        raise AssertionError(
            f"Unexpected persistent fault: {src} @ {loc} "
            f"conf={conf:.3f} (threshold={confidence_threshold}). {msg}",
        )


def assert_no_localized_wheel(
    summary: dict[str, Any],
    *,
    confidence_threshold: float = 0.40,
    msg: str = "",
) -> None:
    """Assert no wheel/tire source is localized to a specific corner above threshold.

    Use for diffuse excitation scenarios where wheel-localization would be a
    false positive.
    """
    for c, conf in _iter_causes_at_or_above(summary, confidence_threshold):
        src = _cause_source(c)
        if "wheel" in src:
            loc = c.get("strongest_location") or ""
            if loc:  # has a location → localized → false positive
                raise AssertionError(
                    f"Wheel/tire falsely localized to '{loc}' conf={conf:.3f}. {msg}",
                )


# ---------------------------------------------------------------------------
# Weird-sensor-mix assertion helpers
# ---------------------------------------------------------------------------

_EXACT_CORNER_TOKENS = (
    "front left",
    "front-left",
    "front_left",
    "front right",
    "front-right",
    "front_right",
    "rear left",
    "rear-left",
    "rear_left",
    "rear right",
    "rear-right",
    "rear_right",
)


def assert_no_exact_corner_claim(
    summary: dict[str, Any],
    *,
    confidence_threshold: float = 0.30,
    msg: str = "",
) -> None:
    """Assert no top cause claims a specific wheel corner above threshold.

    This is stricter than :func:`assert_no_localized_wheel` – it forbids any
    exact-corner string (FL/FR/RL/RR) in ``strongest_location`` regardless of
    source classification.
    """
    for c, conf in _iter_causes_at_or_above(summary, confidence_threshold):
        loc = str(c.get("strongest_location") or "").lower()
        for token in _EXACT_CORNER_TOKENS:
            if token in loc:
                src = _cause_source(c)
                raise AssertionError(
                    f"Exact corner claim '{loc}' from {src} conf={conf:.3f} "
                    f"(threshold={confidence_threshold}). {msg}",
                )


def assert_wheel_weak_spatial(
    summary: dict[str, Any],
    *,
    msg: str = "",
) -> None:
    """Assert that every wheel/tire finding reports weak_spatial_separation.

    Use when the sensor topology cannot support corner-level localization
    (e.g. cabin-only sensors).
    """
    findings = summary.get("findings") or []
    for f in findings:
        src = str(f.get("suspected_source") or "").lower()
        if "wheel" not in src:
            continue
        if str(f.get("finding_id", "")).startswith("REF_"):
            continue
        conf = float(f.get("confidence", 0))
        if conf < 0.10:
            continue
        assert f.get("weak_spatial_separation"), (
            f"Wheel/tire finding '{f.get('finding_key')}' conf={conf:.3f} has "
            f"weak_spatial_separation=False but sensor topology does not support "
            f"corner-level localization. {msg}"
        )


def assert_max_wheel_confidence(
    summary: dict[str, Any],
    max_confidence: float,
    *,
    msg: str = "",
) -> None:
    """Assert no wheel/tire cause exceeds *max_confidence*.

    Use for cabin-only / no-wheel-sensor topologies where wheel confidence
    should be naturally bounded.
    """
    for c in _top_causes(summary):
        src = _cause_source(c)
        if "wheel" not in src:
            continue
        conf = _cause_confidence(c)
        if conf > max_confidence:
            loc = c.get("strongest_location") or ""
            raise AssertionError(
                f"Wheel/tire confidence {conf:.3f} exceeds max {max_confidence:.2f} "
                f"at '{loc}'. {msg}",
            )


def extract_top_finding(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the highest-confidence non-reference finding, or ``None``."""
    findings = summary.get("findings", [])
    non_ref = [
        finding
        for finding in findings
        if isinstance(finding, dict) and not Finding.from_payload(finding).is_reference
    ]
    if not non_ref:
        return None
    return max(non_ref, key=lambda finding: Finding.from_payload(finding).effective_confidence)


def assert_finding_location(
    summary: dict[str, Any],
    expected: str,
    label: str = "",
) -> dict[str, Any]:
    """Assert the top finding's strongest_location contains *expected*."""
    top = extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce at least one diagnostic finding"
    location = str(top.get("strongest_location") or "").lower()
    assert expected in location, (
        f"{label}: Expected '{expected}', got '{top.get('strongest_location')}'"
    )
    return top


def assert_finding_source(
    summary: dict[str, Any],
    expected_sources: tuple[str, ...] = ("wheel", "tire"),
    label: str = "",
) -> dict[str, Any]:
    """Assert the top finding's suspected_source matches one of *expected_sources*."""
    top = extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce a finding"
    source = str(top.get("suspected_source") or "").lower()
    assert any(expected in source for expected in expected_sources), (
        f"{label}: Expected one of {expected_sources}, got '{top.get('suspected_source')}'"
    )
    return top


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
