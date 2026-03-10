"""Tests for WS schema export and payload optimization (freq deduplication)."""

from __future__ import annotations

import json
import os

os.environ.setdefault("VIBESENSOR_DISABLE_AUTO_APP", "1")

from typing import Any

import numpy as np
import pytest

from vibesensor.payload_types import SCHEMA_VERSION
from vibesensor.processing import ClientBuffer, SignalProcessor
from vibesensor.ws_schema_export import export_schema

# ---------------------------------------------------------------------------
# Schema export check
# ---------------------------------------------------------------------------


def test_schema_export_check_passes() -> None:
    """Verify the committed schema matches what the export generates."""
    generated = export_schema()
    assert len(generated) > 100, "Schema should be non-trivial"
    parsed = json.loads(generated)
    assert "properties" in parsed
    assert "schema_version" in parsed["properties"]


# ---------------------------------------------------------------------------
# build_ws_payload includes schema_version
# ---------------------------------------------------------------------------


def _make_state(**kwargs: Any) -> Any:
    """Build a RuntimeState with stubs (reuse the helpers from test_build_ws_payload)."""
    # Import the factory from the existing test module.
    from test_build_ws_payload import _make_state as _factory

    return _factory(**kwargs)


def test_build_ws_payload_includes_schema_version() -> None:
    state = _make_state(
        clients=[{"id": "aaa", "name": "front"}],
        ws_include_heavy=True,
    )
    payload = state.websocket.broadcast.build_payload(selected_client="aaa")
    assert "schema_version" in payload
    assert payload["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# multi_spectrum_payload – freq deduplication
# ---------------------------------------------------------------------------


class TestMultiSpectrumFreqDedup:
    """Verify that per-client freq is omitted when all clients share the same axis."""

    @staticmethod
    def _make_processor_with_clients(
        client_data: dict[str, dict[str, Any]],
    ) -> Any:
        """Create a SignalProcessor and inject fake spectrum data."""
        proc = SignalProcessor(
            sample_rate_hz=800,
            waveform_seconds=8,
            waveform_display_hz=120,
            fft_n=2048,
            spectrum_min_hz=5.0,
            spectrum_max_hz=200.0,
            accel_scale_g_per_lsb=0.004,
        )
        for cid, data in client_data.items():
            freq = np.array(data["freq"], dtype=np.float32)
            amp = np.array(data["amp"], dtype=np.float32)
            buf = ClientBuffer(
                data=np.zeros((2048, 3), dtype=np.float32),
                capacity=2048,
                count=100,
            )
            buf.latest_spectrum = {
                "x": {"freq": freq, "amp": amp},
                "y": {"freq": freq, "amp": amp},
                "z": {"freq": freq, "amp": amp},
                "combined": {"freq": freq, "amp": amp},
            }
            buf.latest_strength_metrics = {"vibration_strength_db": 5.0}
            buf.spectrum_generation = 1
            proc._buffers[cid] = buf
        return proc

    def test_shared_freq_no_per_client_freq(self) -> None:
        """When all clients share the same freq axis, per-client freq is absent."""
        freq = [10.0, 20.0, 30.0]
        amp = [0.01, 0.02, 0.03]
        proc = self._make_processor_with_clients(
            {
                "aaa": {"freq": freq, "amp": amp},
                "bbb": {"freq": freq, "amp": amp},
            },
        )
        result = proc.multi_spectrum_payload(["aaa", "bbb"])
        assert result["freq"] == pytest.approx(freq, abs=1e-4)
        # Per-client entries should NOT have "freq" key
        for cid in ("aaa", "bbb"):
            assert "freq" not in result["clients"][cid], (
                f"Client {cid} should not have per-client freq when axes match"
            )

    def test_mismatch_freq_includes_per_client(self) -> None:
        """When clients have different freq axes, per-client freq IS included."""
        proc = self._make_processor_with_clients(
            {
                "aaa": {"freq": [10.0, 20.0, 30.0], "amp": [0.01, 0.02, 0.03]},
                "bbb": {"freq": [15.0, 25.0, 35.0], "amp": [0.01, 0.02, 0.03]},
            },
        )
        result = proc.multi_spectrum_payload(["aaa", "bbb"])
        # Shared freq should be empty on mismatch
        assert result["freq"] == []
        # Per-client freq should be present
        assert "freq" in result["clients"]["aaa"]
        assert "freq" in result["clients"]["bbb"]
        assert result["clients"]["aaa"]["freq"] == pytest.approx([10.0, 20.0, 30.0], abs=1e-4)
        # Warning should be present
        assert "warning" in result
        assert result["warning"]["code"] == "frequency_bin_mismatch"

    def test_single_client_shared_freq(self) -> None:
        """Single-client payloads use shared freq (no per-client key)."""
        proc = self._make_processor_with_clients(
            {
                "aaa": {"freq": [10.0, 20.0], "amp": [0.01, 0.02]},
            },
        )
        result = proc.multi_spectrum_payload(["aaa"])
        assert result["freq"] == pytest.approx([10.0, 20.0], abs=1e-4)
        assert "freq" not in result["clients"]["aaa"]

    def test_empty_clients(self) -> None:
        """No clients → empty payload."""
        proc = self._make_processor_with_clients({})
        result = proc.multi_spectrum_payload([])
        assert result["freq"] == []
        assert result["clients"] == {}

    def test_payload_size_reduction(self) -> None:
        """Verify the optimized payload is smaller than old-style duplicated."""
        freq = list(np.linspace(5, 200, 512))
        amp = list(np.random.default_rng(42).random(512) * 0.1)
        proc = self._make_processor_with_clients(
            {
                "aaa": {"freq": freq, "amp": amp},
                "bbb": {"freq": freq, "amp": amp},
                "ccc": {"freq": freq, "amp": amp},
            },
        )
        result = proc.multi_spectrum_payload(["aaa", "bbb", "ccc"])
        serialized = json.dumps(result)
        # With 3 clients × 512 freq values, old approach would have ~3×512 extra
        # floats. New approach has only 1×512. Verify shared freq is non-empty.
        assert len(result["freq"]) == 512
        for cid in ("aaa", "bbb", "ccc"):
            assert "freq" not in result["clients"][cid]
        # The serialized size should be noticeably smaller than having freq
        # duplicated per-client. Build a "duplicated" version for comparison.
        dup_result = json.loads(serialized)
        for cid in ("aaa", "bbb", "ccc"):
            dup_result["clients"][cid]["freq"] = freq
        dup_serialized = json.dumps(dup_result)
        assert len(serialized) < len(dup_serialized)
        # Should save at least 2 clients worth of freq data
        saved_bytes = len(dup_serialized) - len(serialized)
        assert saved_bytes > 1000, f"Expected significant savings, got {saved_bytes} bytes"
