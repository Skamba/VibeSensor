"""Regression tests for APSelfHealConfig validation — Grace3 wave fixes.

Prior to the fix, APSelfHealConfig accepted zero or negative integers for
interval_seconds, diagnostics_lookback_minutes, and min_restart_interval_seconds.
That would cause the self-heal watchdog to spin or crash immediately.

These tests would have caught the bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.config import APSelfHealConfig


def _make_self_heal(**overrides) -> APSelfHealConfig:
    """Return an APSelfHealConfig with sensible defaults, applying *overrides*."""
    defaults = {
        "enabled": True,
        "interval_seconds": 60,
        "diagnostics_lookback_minutes": 5,
        "min_restart_interval_seconds": 120,
        "allow_disable_resolved_stub_listener": False,
        "state_file": Path("/tmp/vibesensor_ap_state.json"),
    }
    defaults.update(overrides)
    return APSelfHealConfig(**defaults)  # type: ignore[arg-type]


class TestAPSelfHealIntervalSeconds:
    """interval_seconds must be a positive integer (≥1)."""

    def test_zero_interval_seconds_raises(self) -> None:
        """interval_seconds=0 would cause a tight spin; must be rejected."""
        with pytest.raises(ValueError, match="interval_seconds"):
            _make_self_heal(interval_seconds=0)

    def test_negative_interval_seconds_raises(self) -> None:
        """Negative interval is nonsensical; must be rejected."""
        with pytest.raises(ValueError, match="interval_seconds"):
            _make_self_heal(interval_seconds=-10)

    def test_one_is_minimum_valid_interval(self) -> None:
        """interval_seconds=1 is the lowest valid positive integer."""
        cfg = _make_self_heal(interval_seconds=1)
        assert cfg.interval_seconds == 1

    def test_typical_interval_preserved(self) -> None:
        """Typical interval of 60 s is held unchanged."""
        cfg = _make_self_heal(interval_seconds=60)
        assert cfg.interval_seconds == 60


class TestAPSelfHealDiagnosticsLookback:
    """diagnostics_lookback_minutes must be a positive integer (≥1)."""

    def test_zero_lookback_raises(self) -> None:
        """diagnostics_lookback_minutes=0 is meaningless; must be rejected."""
        with pytest.raises(ValueError, match="diagnostics_lookback_minutes"):
            _make_self_heal(diagnostics_lookback_minutes=0)

    def test_negative_lookback_raises(self) -> None:
        """Negative lookback is not a valid duration."""
        with pytest.raises(ValueError, match="diagnostics_lookback_minutes"):
            _make_self_heal(diagnostics_lookback_minutes=-1)

    def test_one_minute_lookback_valid(self) -> None:
        """diagnostics_lookback_minutes=1 passes validation."""
        cfg = _make_self_heal(diagnostics_lookback_minutes=1)
        assert cfg.diagnostics_lookback_minutes == 1


class TestAPSelfHealMinRestartInterval:
    """min_restart_interval_seconds must be a non-negative integer (≥0)."""

    def test_negative_min_restart_raises(self) -> None:
        """Negative min_restart_interval_seconds must be rejected."""
        with pytest.raises(ValueError, match="min_restart_interval_seconds"):
            _make_self_heal(min_restart_interval_seconds=-1)

    def test_zero_min_restart_allowed(self) -> None:
        """min_restart_interval_seconds=0 is explicitly allowed (no minimum gap)."""
        cfg = _make_self_heal(min_restart_interval_seconds=0)
        assert cfg.min_restart_interval_seconds == 0

    def test_typical_min_restart_preserved(self) -> None:
        """min_restart_interval_seconds=120 passes validation unchanged."""
        cfg = _make_self_heal(min_restart_interval_seconds=120)
        assert cfg.min_restart_interval_seconds == 120


def test_ap_self_heal_valid_defaults_pass() -> None:
    """A fully valid APSelfHealConfig with typical defaults should not raise."""
    cfg = _make_self_heal()
    assert cfg.enabled is True
    assert cfg.interval_seconds > 0
    assert cfg.diagnostics_lookback_minutes > 0
    assert cfg.min_restart_interval_seconds >= 0
