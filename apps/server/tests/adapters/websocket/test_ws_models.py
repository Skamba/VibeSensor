"""Tests for WS schema export and payload optimization (freq deduplication)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from vibesensor.cli.ws_schema_export import export_schema
from vibesensor.infra.processing import ClientBuffer, SignalProcessor
from vibesensor.infra.runtime.ws_broadcast import WsBroadcastService
from vibesensor.shared.types.payload_types import SCHEMA_VERSION, LiveWsPayload
from vibesensor.vibration_strength import empty_vibration_strength_metrics

# ---------------------------------------------------------------------------
# Schema export check
# ---------------------------------------------------------------------------


def test_schema_export_check_passes() -> None:
    """Verify the exported schema exposes the live WS contract shape consumers use."""
    generated = export_schema()
    parsed = json.loads(generated)
    assert parsed["title"] == "LiveWsPayload"
    assert parsed["type"] == "object"

    properties = parsed["properties"]
    assert set(properties) == {
        "schema_version",
        "server_time",
        "speed_mps",
        "clients",
        "selected_client_id",
        "rotational_speeds",
        "spectra",
    }
    assert set(parsed["required"]) == {
        "schema_version",
        "server_time",
        "speed_mps",
        "clients",
        "selected_client_id",
        "rotational_speeds",
    }
    assert properties["spectra"] == {"$ref": "#/$defs/SpectraPayload"}
    assert properties["rotational_speeds"]["anyOf"] == [
        {"$ref": "#/$defs/RotationalSpeedsPayload"},
        {"type": "null"},
    ]

    rotational_speeds = parsed["$defs"]["RotationalSpeedsPayload"]
    assert set(rotational_speeds["required"]) == {
        "basis_speed_source",
        "wheel",
        "driveshaft",
        "engine",
        "order_bands",
    }

    spectra = parsed["$defs"]["SpectraPayload"]
    assert set(spectra["properties"]) == {"alignment", "clients", "freq", "warning"}


# ---------------------------------------------------------------------------
# build_ws_payload includes schema_version
# ---------------------------------------------------------------------------


class _StubPayloadSource:
    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        payload: LiveWsPayload = {
            "schema_version": SCHEMA_VERSION,
            "server_time": "2026-04-05T00:00:00Z",
            "speed_mps": None,
            "clients": [],
            "selected_client_id": None,
            "rotational_speeds": {
                "basis_speed_source": None,
                "wheel": {"rpm": None, "mode": None, "reason": None},
                "driveshaft": {"rpm": None, "mode": None, "reason": None},
                "engine": {"rpm": None, "mode": None, "reason": None},
                "order_bands": None,
            },
        }
        if include_heavy:
            payload["spectra"] = {"freq": [], "clients": {}}
        return payload


def test_build_ws_payload_includes_schema_version() -> None:
    ws_broadcast = WsBroadcastService(
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        payload_source=_StubPayloadSource(),
    )

    payload = ws_broadcast.build_payload(selected_client="aaaaaaaaaaaa")

    assert "schema_version" in payload
    assert payload["schema_version"] == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# multi_spectrum_payload – freq deduplication
# ---------------------------------------------------------------------------


class TestMultiSpectrumFreqDedup:
    """Verify that per-client freq is omitted when all clients share the same axis."""

    @staticmethod
    def _make_processor_with_clients(
        client_data: dict[str, dict[str, list[float]]],
    ) -> SignalProcessor:
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
            buf.latest_strength_metrics = {
                **empty_vibration_strength_metrics(),
                "vibration_strength_db": 5.0,
            }
            buf.spectrum_generation = 1
            proc._store.buffers[cid] = buf
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
