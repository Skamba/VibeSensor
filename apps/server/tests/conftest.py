"""Shared test helpers for the vibesensor test suite."""

from __future__ import annotations

import asyncio
import math
import re
import time
from io import BytesIO
from typing import Any


def wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02) -> bool:
    """Poll *predicate* until it returns truthy, or *timeout_s* expires."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step_s)
    return False


async def async_wait_until(predicate, timeout_s: float = 2.0, step_s: float = 0.02) -> bool:
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
    "confidence_0_to_1",
    "evidence_summary",
    "frequency_hz_or_order",
)

_TOP_CAUSE_REQUIRED_FIELDS = (
    "finding_id",
    "source",
    "confidence",
    "strongest_location",
    "strongest_speed_band",
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
    """Validate a single finding dict satisfies the diagnosis contract.

    Always checks: required fields exist and have non-None values.
    Optionally checks: source, location, speed band, confidence range,
    finding_key, spatial separation.
    """
    # Structural checks
    for field_name in required_fields:
        assert field_name in finding, (
            f"Missing required field '{field_name}' in finding: {list(finding.keys())}"
        )

    # Confidence type + range
    conf = finding.get("confidence_0_to_1")
    assert isinstance(conf, (int, float)), f"confidence_0_to_1 is not numeric: {conf!r}"
    assert not math.isnan(conf), "confidence_0_to_1 is NaN"
    assert confidence_range[0] <= conf <= confidence_range[1], (
        f"confidence_0_to_1 {conf:.3f} not in"
        f" [{confidence_range[0]:.2f}, {confidence_range[1]:.2f}]"
    )

    # Semantic checks (only when arguments provided)
    if expected_source is not None:
        source = str(finding.get("suspected_source", "")).lower()
        assert expected_source.lower() in source, (
            f"Expected source containing {expected_source!r}, got {source!r}"
        )

    if expected_location is not None:
        loc = str(finding.get("strongest_location") or "").lower()
        assert expected_location.lower() in loc, (
            f"Expected location containing {expected_location!r}, got {loc!r}"
        )

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
    """Validate a top_cause dict satisfies the contract.

    Always checks: all required fields exist.
    Optionally checks: source, location, speed band, confidence, signatures.
    """
    for field_name in required_fields:
        assert field_name in top_cause, (
            f"Missing required field '{field_name}' in top_cause: {list(top_cause.keys())}"
        )

    # Confidence type + range
    conf = top_cause.get("confidence", 0.0)
    assert isinstance(conf, (int, float)), f"confidence is not numeric: {conf!r}"
    assert not math.isnan(conf), "confidence is NaN"
    assert confidence_range[0] <= conf <= confidence_range[1], (
        f"confidence {conf:.3f} not in [{confidence_range[0]:.2f}, {confidence_range[1]:.2f}]"
    )

    if expected_source is not None:
        source = str(top_cause.get("source", "")).lower()
        assert expected_source.lower() in source, (
            f"Expected source containing {expected_source!r}, got {source!r}"
        )

    if expected_location is not None:
        loc = str(top_cause.get("strongest_location") or "").lower()
        assert expected_location.lower() in loc, (
            f"Expected location containing {expected_location!r}, got {loc!r}"
        )

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


# ---------------------------------------------------------------------------
# Speed-band parsing helper (internal)
# ---------------------------------------------------------------------------


def _assert_speed_band_overlap(band: str, min_kmh: float, max_kmh: float) -> None:
    """Assert a speed-band string overlaps the given range."""
    assert band and "km/h" in band, f"No valid speed band found: {band!r}"
    m = re.match(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)", band.replace("km/h", "").strip())
    assert m, f"Cannot parse speed band: {band!r}"
    low, high = float(m.group(1)), float(m.group(2))
    assert high > min_kmh and low < max_kmh, (
        f"Speed band {band} ({low}-{high}) does not overlap expected range {min_kmh}-{max_kmh} km/h"
    )
