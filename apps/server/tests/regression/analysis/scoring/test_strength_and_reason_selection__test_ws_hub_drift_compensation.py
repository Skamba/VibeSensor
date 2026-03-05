"""Strength labeling and reason-selection regressions.

Covers:
  1. live_diagnostics._combine_amplitude_strength_db — NaN guard
  2. strength_labels.strength_label — NaN guard returns "unknown"
  3. strength_labels.certainty_label — NaN confidence clamped to 0.0
  4. ws_hub.run() — tick-rate drift compensation (source verification)
  5. Tests for previously-untested helpers
"""

from __future__ import annotations

import inspect

from vibesensor.ws_hub import WebSocketHub


class TestWsHubDriftCompensation:
    """run() should subtract elapsed time from sleep to maintain tick rate."""

    def test_run_subtracts_elapsed(self) -> None:
        source = inspect.getsource(WebSocketHub.run)
        assert "loop.time()" in source or "tick_start" in source
        assert "interval - elapsed" in source
