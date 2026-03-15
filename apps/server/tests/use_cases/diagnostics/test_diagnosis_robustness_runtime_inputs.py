from __future__ import annotations

import math
from typing import Any

import pytest
from test_support import (
    ALL_SENSORS,
    assert_summary_sections,
    assert_top_cause_contract,
    make_sample,
    standard_metadata,
    wheel_hz,
)

from vibesensor.use_cases.diagnostics import summarize_run_data


class TestMissingStaleSpeed:
    def test_zero_speed_throughout_produces_findings_without_crash(self) -> None:
        samples: list[dict[str, Any]] = []
        for i in range(20):
            for sensor in ALL_SENSORS:
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=0.0,
                        client_name=sensor,
                        top_peaks=[{"hz": 25.0, "amp": 0.005}, {"hz": 50.0, "amp": 0.004}],
                        vibration_strength_db=10.0,
                        strength_floor_amp_g=0.003,
                    ),
                )
        summary = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="zero_speed",
        )
        assert "findings" in summary

    def test_nan_speed_samples_do_not_produce_nan_output(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(25):
            speed = 80.0 if i < 20 else float("nan")
            for sensor in ALL_SENSORS:
                if sensor == "front-left" and i < 20:
                    peaks = [{"hz": whz, "amp": 0.06}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )
        summary = summarize_run_data(standard_metadata(), samples, lang="en", file_name="nan_speed")
        for top_cause in summary.get("top_causes", []):
            assert not math.isnan(top_cause.get("confidence", 0))

    def test_stale_speed_partial_run_still_analyses(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(30):
            speed = 80.0 if i < 20 else 0.0
            for sensor in ALL_SENSORS:
                if sensor == "rear-right":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )
        summary = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="stale_speed",
        )
        assert_summary_sections(summary, min_findings=0)


class TestSensorDropoutRejoin:
    def test_sensor_dropout_mid_run_still_localizes(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(90.0)
        for i in range(30):
            for sensor in ALL_SENSORS:
                if sensor == "rear-right" and 15 <= i < 25:
                    continue
                if sensor == "front-left":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=90.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )
        top_causes = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="dropout_test",
        ).get("top_causes", [])
        assert_top_cause_contract(
            top_causes[0],
            expected_source="wheel",
            expected_location="front-left",
            confidence_range=(0.15, 1.0),
        )

    def test_sensor_rejoin_after_gap_does_not_crash(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(40):
            for sensor in ALL_SENSORS:
                if sensor == "rear-left" and 10 <= i < 20:
                    continue
                if sensor == "front-right":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )
        summary = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="rejoin_test",
        )
        assert_summary_sections(summary, min_top_causes=1)
        assert_top_cause_contract(
            summary["top_causes"][0],
            expected_source="wheel",
            expected_location="front-right",
        )


class TestSensorNameNormalization:
    def test_sanitize_name_strips_null_bytes(self) -> None:
        from vibesensor.infra.runtime.registry import _sanitize_name

        assert "\x00" not in _sanitize_name("abc\x00def")

    def test_sanitize_name_strips_control_chars(self) -> None:
        from vibesensor.infra.runtime.registry import _sanitize_name

        result = _sanitize_name("sensor\x01\x02\x03test")
        for char in result:
            assert ord(char) >= 0x20 or char in ("\t", "\n")

    def test_sanitize_name_handles_emoji_truncation(self) -> None:
        from vibesensor.infra.runtime.registry import _sanitize_name

        result = _sanitize_name("🔧" * 10)
        result.encode("utf-8")
        assert len(result.encode("utf-8")) <= 32

    @pytest.mark.smoke
    def test_sanitize_name_empty_returns_empty(self) -> None:
        from vibesensor.infra.runtime.registry import _sanitize_name

        assert _sanitize_name("") == ""
        assert _sanitize_name("   ") == ""

    def test_sensor_name_case_variations_in_report(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(20):
            for sensor in ["Front-Left", "front-right", "REAR-LEFT", "Rear-Right"]:
                if sensor.lower() == "front-right":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    ),
                )
        summary = summarize_run_data(
            standard_metadata(),
            samples,
            lang="en",
            file_name="case_mix_test",
        )
        assert_summary_sections(summary, min_top_causes=1)
        assert "wheel" in str(summary["top_causes"][0].get("suspected_source", "")).lower()


class TestGpsSpeedValidation:
    @staticmethod
    def tpv_line(speed_value: object) -> bytes:
        import json as json_module

        return (
            json_module.dumps(
                {
                    "class": "TPV",
                    "mode": 3,
                    "eph": 10.0,
                    "eps": 0.5,
                    "lat": 54.6872,
                    "lon": 25.2797,
                    "speed": speed_value,
                },
            ).encode()
            + b"\n"
        )

    @staticmethod
    def valid_tpv_line(speed: float = 25.5) -> bytes:
        import json as json_module

        return (
            json_module.dumps(
                {
                    "class": "TPV",
                    "mode": 3,
                    "eph": 10.0,
                    "eps": 0.5,
                    "lat": 54.6872,
                    "lon": 25.2797,
                    "speed": speed,
                },
            ).encode()
            + b"\n"
        )

    @pytest.mark.parametrize(
        ("bad_speed", "label"),
        [
            (float("nan"), "NaN"),
            (float("inf"), "Inf"),
            (-5.0, "Negative"),
            (None, "None"),
            ("fast", "String"),
        ],
        ids=["nan", "inf", "negative", "none", "string"],
    )
    def test_invalid_speed_rejected_by_product_code(self, bad_speed: object, label: str) -> None:
        import asyncio

        from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor

        monitor = GPSSpeedMonitor(gps_enabled=True)

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(self.valid_tpv_line(10.0))
            await writer.drain()
            await asyncio.sleep(0.05)
            writer.write(self.tpv_line(bad_speed))
            await writer.drain()
            await asyncio.sleep(0.3)
            writer.close()
            await writer.wait_closed()

        async def run() -> None:
            server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
            host, port = server.sockets[0].getsockname()[:2]
            task = asyncio.create_task(monitor.run(host=host, port=port))
            for _ in range(60):
                if monitor.speed_mps is not None:
                    break
                await asyncio.sleep(0.05)
            assert monitor.speed_mps == 10.0
            await asyncio.sleep(0.15)
            assert monitor.speed_mps == 10.0, (
                f"{label} speed leaked into speed_mps: {monitor.speed_mps}"
            )
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            server.close()
            await server.wait_closed()

        asyncio.run(run())
