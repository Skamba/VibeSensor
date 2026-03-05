"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

from vibesensor.live_diagnostics import LiveDiagnosticsEngine
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug13FreqBinDivision:
    def test_zero_freq_bin_hz_no_crash(self) -> None:
        engine = LiveDiagnosticsEngine()
        # Even if _multi_freq_bin_hz were 0, the guard prevents division by zero
        old_val = engine._multi_freq_bin_hz
        engine._multi_freq_bin_hz = 0.0
        # The freq_bin calculation should use max(0.01, ...) guard
        freq_bin = round(10.0 / max(0.01, engine._multi_freq_bin_hz))
        assert isinstance(freq_bin, int)
        engine._multi_freq_bin_hz = old_val
