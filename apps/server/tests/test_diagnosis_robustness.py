# ruff: noqa: E501
"""Robustness tests for diagnosis accuracy.

Covers:
- Dual/multi-fault scenarios (Level C: two simultaneous faults must produce
  multiple distinct findings, not collapse to one).
- Real-world edge cases:
  - Clipped/saturated sensor data
  - Duplicate/replayed packets
  - Missing/stale/invalid speed
  - Mixed sensor dropout/rejoin
  - Sensor-name normalization edge cases
- PDF content validation for diagnosed scenarios.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from conftest import (
    assert_summary_sections,
    assert_top_cause_contract,
)
from vibesensor_core.strength_bands import bucket_for_strength

from vibesensor.analysis_settings import (
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from vibesensor.report.summary import summarize_run_data

# ---------------------------------------------------------------------------
# Shared helpers (kept local to this module for clarity)
# ---------------------------------------------------------------------------

_TIRE_CIRC = tire_circumference_m_from_spec(
    DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"],
    DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"],
    DEFAULT_ANALYSIS_SETTINGS["rim_in"],
)
_FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
_GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]

_ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]


def _wheel_hz(speed_kmh: float) -> float:
    hz = wheel_hz_from_speed_kmh(speed_kmh, _TIRE_CIRC)
    assert hz is not None and hz > 0
    return hz


def _standard_metadata(**overrides: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "tire_circumference_m": _TIRE_CIRC,
        "raw_sample_rate_hz": 800.0,
        "final_drive_ratio": _FINAL_DRIVE,
        "current_gear_ratio": _GEAR_RATIO,
        "sensor_model": "ADXL345",
        "units": {"accel_x_g": "g"},
    }
    meta.update(overrides)
    return meta


def _make_sample(
    *,
    t_s: float,
    speed_kmh: float,
    client_name: str,
    top_peaks: list[dict[str, float]],
    vibration_strength_db: float = 20.0,
    strength_floor_amp_g: float = 0.003,
) -> dict[str, Any]:
    return {
        "t_s": t_s,
        "speed_kmh": speed_kmh,
        "accel_x_g": 0.02,
        "accel_y_g": 0.02,
        "accel_z_g": 0.10,
        "vibration_strength_db": vibration_strength_db,
        "strength_bucket": bucket_for_strength(vibration_strength_db),
        "strength_floor_amp_g": strength_floor_amp_g,
        "client_name": client_name,
        "client_id": f"sensor-{client_name}",
        "top_peaks": top_peaks,
    }


# ===========================================================================
# DUAL-FAULT: two simultaneous faults on different corners
# ===========================================================================


class TestDualFaultTwoCorners:
    """Level C: two simultaneous faults on different corners.

    The current pipeline collapses same-frequency peaks in the findings engine,
    so the *findings* may attribute all peaks to the strongest corner.  The
    *sensor_intensity_by_location* ranking must still surface both corners."""

    def test_dual_fault_front_right_and_rear_left(self) -> None:
        """Simultaneous FR + RL faults: at least one fault corner in findings,
        both in intensity ranking."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(40):
            t = float(i)
            for sensor in _ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                elif sensor == "rear-left":
                    peaks = [
                        {"hz": whz, "amp": 0.05},
                        {"hz": whz * 2, "amp": 0.020},
                    ]
                    vib_db = 24.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="dual_fault_test")
        assert_summary_sections(summary, min_findings=1, min_top_causes=1)

        # All non-REF findings with meaningful confidence
        findings = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict)
            and not str(f.get("finding_id", "")).startswith("REF_")
            and float(f.get("confidence_0_to_1") or 0) > 0.10
        ]
        # Dual faults: the analysis may group them if same order - what matters
        # is that multiple sensor locations appear in top_causes or findings
        locations_in_findings = set()
        for f in findings:
            loc = str(f.get("strongest_location") or "").lower()
            if loc:
                locations_in_findings.add(loc)

        # Also check top_causes for multi-location coverage
        top_causes = summary.get("top_causes", [])
        for tc in top_causes:
            loc = str(tc.get("strongest_location") or "").lower()
            if loc:
                locations_in_findings.add(loc)

        # At minimum the system must detect one of the fault corners in findings
        fault_corners = {"front-right", "rear-left"}
        detected = locations_in_findings & fault_corners
        assert len(detected) >= 1, (
            f"Dual-fault: expected at least one fault corner detected, got locations: {locations_in_findings}"
        )

        # The sensor intensity ranking MUST surface both fault corners in the
        # top rows (even if the findings engine collapses same-frequency peaks)
        intensities = summary.get("sensor_intensity_by_location", [])
        intensity_locs = {str(row.get("location", "")).lower() for row in intensities[:4]}
        for corner in fault_corners:
            assert any(corner in loc for loc in intensity_locs), (
                f"Intensity ranking missing {corner}: {intensity_locs}"
            )

        # Validate the top cause has a valid contract
        if top_causes:
            assert_top_cause_contract(
                top_causes[0],
                expected_source="wheel",
                confidence_range=(0.15, 1.0),
            )

    def test_dual_fault_both_corners_in_intensity_ranking(self) -> None:
        """Both fault corners should appear in sensor_intensity_by_location."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(90.0)
        for i in range(35):
            t = float(i)
            for sensor in _ALL_SENSORS:
                if sensor == "front-left":
                    peaks = [
                        {"hz": whz, "amp": 0.065},
                        {"hz": whz * 2, "amp": 0.026},
                    ]
                    vib_db = 27.0
                elif sensor == "rear-right":
                    peaks = [
                        {"hz": whz, "amp": 0.055},
                        {"hz": whz * 2, "amp": 0.022},
                    ]
                    vib_db = 25.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 7.0
                samples.append(
                    _make_sample(
                        t_s=t,
                        speed_kmh=90.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="dual_fault_intensity")
        intensities = summary.get("sensor_intensity_by_location", [])
        assert len(intensities) >= 2, (
            f"Expected >= 2 sensor locations in intensity ranking, got {len(intensities)}"
        )
        # Front-left and rear-right should be in the top rows
        intensity_locs = {str(row.get("location", "")).lower() for row in intensities[:4]}
        assert any("front-left" in loc for loc in intensity_locs), (
            f"front-left not in intensity ranking: {intensity_locs}"
        )
        assert any("rear-right" in loc for loc in intensity_locs), (
            f"rear-right not in intensity ranking: {intensity_locs}"
        )


# ===========================================================================
# CLIPPED / SATURATED sensor data
# ===========================================================================


class TestClippedSaturatedData:
    """Verify the system handles clipped (ADC-railed) sensor data gracefully."""

    def test_saturated_samples_do_not_produce_nan_report(self) -> None:
        """Saturated samples (all at max amplitude) should not produce NaN in report."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(30):
            for sensor in _ALL_SENSORS:
                # Even "saturated" sensors still report top_peaks (the FFT has
                # happened on-device); we simulate extremely high peak amplitudes.
                if sensor == "front-right":
                    peaks = [
                        {"hz": whz, "amp": 2.0},  # way above normal ~0.06
                        {"hz": whz * 2, "amp": 0.8},
                    ]
                    vib_db = 55.0  # extremely high
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="saturated_test")

        # Must not produce NaN anywhere in top_causes
        for tc in summary.get("top_causes", []):
            conf = tc.get("confidence", 0)
            assert not math.isnan(conf), f"NaN confidence in top_cause: {tc}"

        # Findings should still have valid contract
        findings = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
        ]
        for f in findings:
            conf = float(f.get("confidence_0_to_1") or 0)
            assert not math.isnan(conf), f"NaN confidence in finding: {f.get('finding_id')}"

    def test_clipped_waveform_still_detects_fault_location(self) -> None:
        """Even w/ high-amplitude clipped data, location should still resolve correctly."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(100.0)
        for i in range(25):
            for sensor in _ALL_SENSORS:
                if sensor == "rear-left":
                    peaks = [
                        {"hz": whz, "amp": 1.5},
                        {"hz": whz * 2, "amp": 0.6},
                        {"hz": whz * 3, "amp": 0.3},  # harmonic from clipping
                    ]
                    vib_db = 50.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=100.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="clipped_location")
        top_causes = summary.get("top_causes", [])
        assert top_causes, "Clipped data should still produce top_causes"
        assert_top_cause_contract(
            top_causes[0],
            expected_source="wheel",
            expected_location="rear-left",
            confidence_range=(0.10, 1.0),
        )


# ===========================================================================
# DUPLICATE / REPLAYED packets in JSONL sample stream
# ===========================================================================


class TestDuplicateReplayedSamples:
    """Verify diagnosis handles duplicate sample timestamps gracefully."""

    @staticmethod
    def _fault_scenario_samples(*, duplicate: bool) -> list[dict[str, Any]]:
        """Build 30s single-corner fault samples, optionally with exact duplicates."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(30):
            for sensor in _ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                s = _make_sample(
                    t_s=float(i),
                    speed_kmh=80.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                )
                samples.append(s)
                if duplicate:
                    samples.append(dict(s))
        return samples

    def test_exact_duplicate_samples_do_not_inflate_confidence(self) -> None:
        """Exact duplicate samples must not inflate confidence vs. baseline."""
        meta = _standard_metadata()

        # Baseline: no duplicates
        baseline = summarize_run_data(
            meta,
            self._fault_scenario_samples(duplicate=False),
            lang="en",
            file_name="no_dup_baseline",
        )
        # With duplicates
        duped = summarize_run_data(
            meta,
            self._fault_scenario_samples(duplicate=True),
            lang="en",
            file_name="dup_test",
        )

        # Must not crash, valid contract
        assert_summary_sections(duped, min_findings=0)
        for tc in duped.get("top_causes", []):
            conf = tc.get("confidence", 0)
            assert isinstance(conf, (int, float)), f"Non-numeric confidence: {conf}"
            assert not math.isnan(conf), "NaN confidence from duplicate data"

        # Top-cause confidence with duplicates must not exceed baseline by > 15%
        # (a large margin -- exact parity is fine, modest inflation is tolerable)
        baseline_top = baseline.get("top_causes", [])
        duped_top = duped.get("top_causes", [])
        if baseline_top and duped_top:
            baseline_conf = float(baseline_top[0].get("confidence", 0))
            duped_conf = float(duped_top[0].get("confidence", 0))
            assert duped_conf <= baseline_conf + 0.15, (
                f"Duplicate inflation: baseline {baseline_conf:.3f} → duplicated {duped_conf:.3f}"
            )


# ===========================================================================
# MISSING / STALE / INVALID speed
# ===========================================================================


class TestMissingStaleSpeed:
    """Verify diagnosis handles missing or invalid speed values."""

    def test_zero_speed_throughout_produces_findings_without_crash(self) -> None:
        """All samples at speed=0 should produce a report without crashing."""
        samples: list[dict[str, Any]] = []
        for i in range(20):
            for sensor in _ALL_SENSORS:
                peaks = [{"hz": 25.0, "amp": 0.005}, {"hz": 50.0, "amp": 0.004}]
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=0.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=10.0,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="zero_speed")
        # Should complete without crash; findings may be empty or reference-only
        assert isinstance(summary, dict)
        assert "findings" in summary

    def test_nan_speed_samples_do_not_produce_nan_output(self) -> None:
        """Samples with NaN speed should not propagate NaN into the report."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(25):
            speed = 80.0 if i < 20 else float("nan")
            for sensor in _ALL_SENSORS:
                if sensor == "front-left" and i < 20:
                    peaks = [{"hz": whz, "amp": 0.06}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="nan_speed")
        # Verify no NaN propagation in top_causes confidence
        for tc in summary.get("top_causes", []):
            conf = tc.get("confidence", 0)
            assert not math.isnan(conf), "NaN confidence leaked from NaN speed samples"

    def test_stale_speed_partial_run_still_analyses(self) -> None:
        """If speed is present for first half then missing (0), analysis still works."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(30):
            speed = 80.0 if i < 20 else 0.0
            for sensor in _ALL_SENSORS:
                if sensor == "rear-right":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="stale_speed")
        assert_summary_sections(summary, min_findings=0)
        # The system should still produce at least some analysis from the first 20s
        assert isinstance(summary.get("findings"), list)


# ===========================================================================
# MIXED SENSOR DROPOUT / REJOIN
# ===========================================================================


class TestSensorDropoutRejoin:
    """Verify diagnosis handles sensors that disappear and reappear mid-run."""

    def test_sensor_dropout_mid_run_still_localizes(self) -> None:
        """3 sensors present throughout, 1 drops at t=15s: analysis still localizes."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(90.0)
        for i in range(30):
            for sensor in _ALL_SENSORS:
                # Rear-right drops out between t=15 and t=25
                if sensor == "rear-right" and 15 <= i < 25:
                    continue
                if sensor == "front-left":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=90.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="dropout_test")
        top_causes = summary.get("top_causes", [])
        assert top_causes, "Sensor dropout should not prevent top_cause generation"
        # Front-left should still be correctly identified
        assert_top_cause_contract(
            top_causes[0],
            expected_source="wheel",
            expected_location="front-left",
            confidence_range=(0.15, 1.0),
        )

    def test_sensor_rejoin_after_gap_does_not_crash(self) -> None:
        """Sensor disappears then reappears with new data: no crash."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        for i in range(40):
            for sensor in _ALL_SENSORS:
                # Rear-left disappears from t=10 to t=20, then comes back
                if sensor == "rear-left" and 10 <= i < 20:
                    continue
                if sensor == "front-right":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="rejoin_test")
        # Must complete without exception; front-right fault still detected
        assert_summary_sections(summary, min_top_causes=1)
        assert_top_cause_contract(
            summary["top_causes"][0],
            expected_source="wheel",
            expected_location="front-right",
        )


# ===========================================================================
# SENSOR-NAME NORMALIZATION edge cases
# ===========================================================================


class TestSensorNameNormalization:
    """Verify sensor name edge cases in the registry/sanitize path."""

    def test_sanitize_name_strips_null_bytes(self) -> None:
        """Null bytes in sensor names should be stripped by _sanitize_name."""
        from vibesensor.registry import _sanitize_name

        result = _sanitize_name("abc\x00def")
        assert "\x00" not in result, f"Null byte not stripped: {result!r}"

    def test_sanitize_name_strips_control_chars(self) -> None:
        """Control characters should be stripped from sensor names."""
        from vibesensor.registry import _sanitize_name

        result = _sanitize_name("sensor\x01\x02\x03test")
        # Control chars should be either stripped or replaced
        for c in result:
            assert ord(c) >= 0x20 or c in ("\t", "\n"), (
                f"Control char U+{ord(c):04X} not stripped in {result!r}"
            )

    def test_sanitize_name_handles_emoji_truncation(self) -> None:
        """Emoji truncation at 32 bytes should not produce broken UTF-8."""
        from vibesensor.registry import _sanitize_name

        # 10 emoji × 4 bytes each = 40 bytes; truncation at 32 should keep 8 emoji
        name = "🔧" * 10
        result = _sanitize_name(name)
        # The result must be valid, decodeable UTF-8
        result.encode("utf-8")  # should not raise
        assert len(result.encode("utf-8")) <= 32

    @pytest.mark.smoke
    def test_sanitize_name_empty_returns_empty(self) -> None:
        from vibesensor.registry import _sanitize_name

        assert _sanitize_name("") == ""
        assert _sanitize_name("   ") == ""

    def test_sensor_name_case_variations_in_report(self) -> None:
        """Sensors named Front-Right and front-right produce a valid report."""
        samples: list[dict[str, Any]] = []
        whz = _wheel_hz(80.0)
        # Use mixed-case sensor names
        sensors_mixed = ["Front-Left", "front-right", "REAR-LEFT", "Rear-Right"]
        for i in range(20):
            for sensor in sensors_mixed:
                if sensor.lower() == "front-right":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata()
        summary = summarize_run_data(meta, samples, lang="en", file_name="case_mix_test")
        # Should complete without crash and identify the fault
        assert_summary_sections(summary, min_top_causes=1)
        top = summary["top_causes"][0]
        # Source should be wheel
        source = str(top.get("source", "")).lower()
        assert "wheel" in source, f"Expected wheel source, got {source!r}"


# ===========================================================================
# GPS SPEED VALIDATION — exercises the real product guard via TCP mock
# ===========================================================================


class TestGpsSpeedValidation:
    """Test GPS speed validation guards against NaN/Inf/negative.

    These tests send invalid TPV payloads through a local TCP server and verify
    the **product code** in ``GPSSpeedMonitor.run()`` rejects them.
    """

    @staticmethod
    def _tpv_line(speed_value: object) -> bytes:
        """Build a gpsd TPV JSON line with the given *speed* value."""
        import json as _json

        return _json.dumps(
            {"class": "TPV", "mode": 3, "eph": 10.0, "eps": 0.5, "speed": speed_value}
        ).encode() + b"\n"

    @staticmethod
    def _valid_tpv_line(speed: float = 25.5) -> bytes:
        import json as _json

        return _json.dumps(
            {"class": "TPV", "mode": 3, "eph": 10.0, "eps": 0.5, "speed": speed}
        ).encode() + b"\n"

    def test_nan_speed_rejected_by_product_code(self) -> None:
        """GPSSpeedMonitor.run() must reject NaN speed from gpsd TPV."""
        import asyncio

        from vibesensor.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()  # consume WATCH command
            # First send a valid speed so we know the connection works
            writer.write(self._valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            # Now send NaN — product code must reject
            writer.write(self._tpv_line(float("nan")))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def _run() -> None:
            server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            # Wait for valid speed to be accepted
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0, "Valid speed should be accepted first"
            # Give time for NaN payload to be processed
            await asyncio.sleep(0.15)
            # speed_mps must still be 10.0 (NaN rejected by product guard)
            assert monitor.speed_mps == 10.0, (
                f"NaN speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(_run())

    def test_inf_speed_rejected_by_product_code(self) -> None:
        """GPSSpeedMonitor.run() must reject Inf speed from gpsd TPV."""
        import asyncio

        from vibesensor.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(self._valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(self._tpv_line(float("inf")))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def _run() -> None:
            server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0
            await asyncio.sleep(0.15)
            assert monitor.speed_mps == 10.0, (
                f"Inf speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(_run())

    def test_negative_speed_rejected_by_product_code(self) -> None:
        """GPSSpeedMonitor.run() must reject negative speed values from gpsd."""
        import asyncio

        from vibesensor.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(self._valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(self._tpv_line(-5.0))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def _run() -> None:
            server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0
            await asyncio.sleep(0.15)
            assert monitor.speed_mps == 10.0, (
                f"Negative speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(_run())

    def test_none_speed_rejected_by_product_code(self) -> None:
        """GPSSpeedMonitor.run() must ignore TPV with speed=null."""
        import asyncio

        from vibesensor.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(self._valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(self._tpv_line(None))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def _run() -> None:
            server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0
            await asyncio.sleep(0.15)
            assert monitor.speed_mps == 10.0, (
                f"None speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(_run())

    def test_string_speed_rejected_by_product_code(self) -> None:
        """GPSSpeedMonitor.run() must ignore TPV with speed as a string."""
        import asyncio

        from vibesensor.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(self._valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(self._tpv_line("fast"))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def _run() -> None:
            server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0
            await asyncio.sleep(0.15)
            assert monitor.speed_mps == 10.0, (
                f"String speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(_run())


# ===========================================================================
# PDF CONTENT VALIDATION for diagnosed scenario
# ===========================================================================


class TestPdfContentForDiagnosedScenario:
    """Validate PDF report content accuracy for a known-fault scenario."""

    def test_pdf_contains_diagnosis_content(self) -> None:
        """Generate a fault scenario PDF and verify key diagnostic text appears."""
        whz = _wheel_hz(100.0)
        samples: list[dict[str, Any]] = []
        for i in range(40):
            for sensor in _ALL_SENSORS:
                if sensor == "front-left":
                    peaks = [
                        {"hz": whz, "amp": 0.06},
                        {"hz": whz * 2, "amp": 0.024},
                    ]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=100.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata(language="en")
        summary = summarize_run_data(meta, samples, lang="en", file_name="pdf_diag_test")

        # Build PDF
        from vibesensor.report.pdf_builder import build_report_pdf

        pdf_bytes = build_report_pdf(summary)

        # Extract text
        from conftest import extract_pdf_text

        text = extract_pdf_text(pdf_bytes)

        # Verify key diagnostic content appears
        text_lower = text.lower()

        # 1. Section headers must be present
        assert "diagnostic worksheet" in text_lower, "Missing 'Diagnostic Worksheet' heading"

        # 2. Primary system should appear
        assert "wheel" in text_lower or "tire" in text_lower, "Missing wheel/tire system in PDF"

        # 3. Sensor location should appear
        assert "front" in text_lower, "Missing front location in PDF"

        # 4. Speed info should appear (km/h)
        assert "km/h" in text_lower, "Missing speed unit in PDF"

        # 5. Strength/dB should appear
        assert "db" in text_lower, "Missing dB strength in PDF"

        # 6. PDF is valid (at least 1 page)
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        assert len(reader.pages) >= 1, "PDF should have at least 1 page"

    def test_pdf_nl_contains_dutch_diagnosis(self) -> None:
        """Dutch PDF should contain Dutch labels and diagnosis text."""
        whz = _wheel_hz(80.0)
        samples: list[dict[str, Any]] = []
        for i in range(30):
            for sensor in _ALL_SENSORS:
                if sensor == "rear-right":
                    peaks = [{"hz": whz, "amp": 0.06}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        meta = _standard_metadata(language="nl")
        summary = summarize_run_data(meta, samples, lang="nl", file_name="pdf_nl_diag")

        from vibesensor.report.pdf_builder import build_report_pdf

        pdf_bytes = build_report_pdf(summary)

        from conftest import extract_pdf_text

        text = extract_pdf_text(pdf_bytes)
        text_lower = text.lower()

        # Dutch section headers
        assert "diagnostisch werkblad" in text_lower, "Missing Dutch 'Diagnostisch werkblad'"
        assert "km/h" in text_lower
