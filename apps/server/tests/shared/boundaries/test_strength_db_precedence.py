"""Tests for strength_db fallback precedence in resolve_primary_report_facts."""

from __future__ import annotations

from vibesensor.domain import Finding, LocationIntensitySummary, RunCapture, TestRun
from vibesensor.shared.boundaries.report_projection import (
    resolve_primary_report_facts,
    sensor_fallback_strength_db,
)


def _make_test_run(
    *,
    strength_db: float | None = None,
    findings: tuple[Finding, ...] | None = None,
) -> TestRun:
    """Build a minimal TestRun with an optional finding that carries strength_db."""
    if findings is not None:
        f_list = findings
    elif strength_db is not None:
        f_list = (
            Finding(
                finding_id="F001",
                confidence=0.80,
                suspected_source="wheel/tire",
                vibration_strength_db=strength_db,
            ),
        )
    else:
        f_list = (
            Finding(
                finding_id="F001",
                confidence=0.80,
                suspected_source="wheel/tire",
            ),
        )
    return TestRun(
        capture=RunCapture(run_id="precedence-test"),
        findings=f_list,
        top_causes=f_list[:1],
    )


def _sensor_intensity(p95: float) -> list[LocationIntensitySummary]:
    return [LocationIntensitySummary(location="front", p95_intensity_db=p95)]


def _resolve_strength_db(
    run: TestRun,
    *,
    sensor_intensity: list[LocationIntensitySummary],
) -> float | None:
    """Resolve report facts and return only the strength_db under test."""
    return resolve_primary_report_facts(
        aggregate=run,
        origin_location="",
        sensor_locations_active=["front"],
        sensor_intensity=sensor_intensity,
    ).strength_db


# ---------------------------------------------------------------------------
# Precedence tier 1: domain-derived strength takes priority
# ---------------------------------------------------------------------------


def test_domain_strength_takes_precedence_over_sensor_fallback() -> None:
    """When domain aggregate provides strength_db, sensor fallback is ignored."""
    run = _make_test_run(strength_db=25.0)
    assert _resolve_strength_db(run, sensor_intensity=_sensor_intensity(18.0)) == 25.0


# ---------------------------------------------------------------------------
# Precedence tier 2: sensor fallback when domain has no strength
# ---------------------------------------------------------------------------


def test_sensor_fallback_used_when_domain_strength_is_none() -> None:
    """When no finding has vibration_strength_db, sensor p95 is the fallback."""
    run = _make_test_run(strength_db=None)
    assert _resolve_strength_db(run, sensor_intensity=_sensor_intensity(18.0)) == 18.0


# ---------------------------------------------------------------------------
# Precedence tier 3: both sources absent → None
# ---------------------------------------------------------------------------


def test_strength_db_is_none_when_both_sources_absent() -> None:
    """When neither domain nor sensor provides strength_db, result is None."""
    run = _make_test_run(strength_db=None)
    assert _resolve_strength_db(run, sensor_intensity=[]) is None


# ---------------------------------------------------------------------------
# sensor_fallback_strength_db edge cases
# ---------------------------------------------------------------------------


def test_sensor_fallback_returns_max_p95() -> None:
    """sensor_fallback_strength_db returns the maximum p95 across locations."""
    intensity = [
        LocationIntensitySummary(location="front", p95_intensity_db=15.0),
        LocationIntensitySummary(location="rear", p95_intensity_db=22.0),
        LocationIntensitySummary(location="trunk", p95_intensity_db=10.0),
    ]
    assert sensor_fallback_strength_db(intensity) == 22.0


def test_sensor_fallback_skips_none_values() -> None:
    """sensor_fallback_strength_db ignores locations with None p95."""
    intensity = [
        LocationIntensitySummary(location="front", p95_intensity_db=None),
        LocationIntensitySummary(location="rear", p95_intensity_db=12.0),
    ]
    assert sensor_fallback_strength_db(intensity) == 12.0


def test_sensor_fallback_returns_none_for_empty_input() -> None:
    """sensor_fallback_strength_db returns None for empty sensor list."""
    assert sensor_fallback_strength_db([]) is None
