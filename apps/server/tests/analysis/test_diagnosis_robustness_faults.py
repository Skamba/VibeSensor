# ruff: noqa: E501
from __future__ import annotations

import math
from typing import Any

import pytest
from _diagnosis_robustness_helpers import (
    ALL_SENSORS,
    assert_summary_sections,
    assert_top_cause_contract,
    make_sample,
    standard_metadata,
    summarize_run_data,
    wheel_hz,
)


class TestDualFaultTwoCorners:
    @pytest.mark.xfail(
        reason="Pipeline collapses same-order dual faults into single finding (GH-292)",
        strict=False,
    )
    def test_dual_fault_front_right_and_rear_left(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(40):
            t = float(i)
            for sensor in ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                elif sensor == "rear-left":
                    peaks = [{"hz": whz, "amp": 0.05}, {"hz": whz * 2, "amp": 0.020}]
                    vib_db = 24.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        summary = summarize_run_data(
            standard_metadata(), samples, lang="en", file_name="dual_fault_test"
        )
        assert_summary_sections(summary, min_findings=1, min_top_causes=1)
        findings = [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict)
            and not str(f.get("finding_id", "")).startswith("REF_")
            and float(f.get("confidence_0_to_1") or 0) > 0.10
        ]
        locations = {
            str(f.get("strongest_location") or "").lower()
            for f in findings
            if str(f.get("strongest_location") or "")
        }
        for top_cause in summary.get("top_causes", []):
            loc = str(top_cause.get("strongest_location") or "").lower()
            if loc:
                locations.add(loc)
        assert len(locations & {"front-right", "rear-left"}) >= 2
        intensity_locs = {
            str(row.get("location", "")).lower()
            for row in summary.get("sensor_intensity_by_location", [])[:4]
        }
        for corner in {"front-right", "rear-left"}:
            assert any(corner in loc for loc in intensity_locs)
        if summary.get("top_causes"):
            assert_top_cause_contract(
                summary["top_causes"][0], expected_source="wheel", confidence_range=(0.15, 1.0)
            )

    def test_dual_fault_both_corners_in_intensity_ranking(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(90.0)
        for i in range(35):
            t = float(i)
            for sensor in ALL_SENSORS:
                if sensor == "front-left":
                    peaks = [{"hz": whz, "amp": 0.065}, {"hz": whz * 2, "amp": 0.026}]
                    vib_db = 27.0
                elif sensor == "rear-right":
                    peaks = [{"hz": whz, "amp": 0.055}, {"hz": whz * 2, "amp": 0.022}]
                    vib_db = 25.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 7.0
                samples.append(
                    make_sample(
                        t_s=t,
                        speed_kmh=90.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )

        intensities = summarize_run_data(
            standard_metadata(), samples, lang="en", file_name="dual_fault_intensity"
        ).get("sensor_intensity_by_location", [])
        intensity_locs = {str(row.get("location", "")).lower() for row in intensities[:4]}
        assert any("front-left" in loc for loc in intensity_locs)
        assert any("rear-right" in loc for loc in intensity_locs)


class TestClippedSaturatedData:
    def test_saturated_samples_do_not_produce_nan_report(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(30):
            for sensor in ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [{"hz": whz, "amp": 2.0}, {"hz": whz * 2, "amp": 0.8}]
                    vib_db = 55.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=80.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )
        summary = summarize_run_data(
            standard_metadata(), samples, lang="en", file_name="saturated_test"
        )
        for top_cause in summary.get("top_causes", []):
            assert not math.isnan(top_cause.get("confidence", 0))
        for finding in [
            f
            for f in summary.get("findings", [])
            if isinstance(f, dict) and not str(f.get("finding_id", "")).startswith("REF_")
        ]:
            assert not math.isnan(float(finding.get("confidence_0_to_1") or 0))

    def test_clipped_waveform_still_detects_fault_location(self) -> None:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(100.0)
        for i in range(25):
            for sensor in ALL_SENSORS:
                if sensor == "rear-left":
                    peaks = [
                        {"hz": whz, "amp": 1.5},
                        {"hz": whz * 2, "amp": 0.6},
                        {"hz": whz * 3, "amp": 0.3},
                    ]
                    vib_db = 50.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.004}]
                    vib_db = 8.0
                samples.append(
                    make_sample(
                        t_s=float(i),
                        speed_kmh=100.0,
                        client_name=sensor,
                        top_peaks=peaks,
                        vibration_strength_db=vib_db,
                        strength_floor_amp_g=0.003,
                    )
                )
        top_causes = summarize_run_data(
            standard_metadata(), samples, lang="en", file_name="clipped_location"
        ).get("top_causes", [])
        assert_top_cause_contract(
            top_causes[0],
            expected_source="wheel",
            expected_location="rear-left",
            confidence_range=(0.10, 1.0),
        )


class TestDuplicateReplayedSamples:
    @staticmethod
    def fault_scenario_samples(*, duplicate: bool) -> list[dict[str, Any]]:
        samples: list[dict[str, Any]] = []
        whz = wheel_hz(80.0)
        for i in range(30):
            for sensor in ALL_SENSORS:
                if sensor == "front-right":
                    peaks = [{"hz": whz, "amp": 0.06}, {"hz": whz * 2, "amp": 0.024}]
                    vib_db = 26.0
                else:
                    peaks = [{"hz": 142.5, "amp": 0.003}]
                    vib_db = 8.0
                current_sample = make_sample(
                    t_s=float(i),
                    speed_kmh=80.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vib_db,
                    strength_floor_amp_g=0.003,
                )
                samples.append(current_sample)
                if duplicate:
                    samples.append(dict(current_sample))
        return samples

    def test_exact_duplicate_samples_do_not_inflate_confidence(self) -> None:
        baseline = summarize_run_data(
            standard_metadata(),
            self.fault_scenario_samples(duplicate=False),
            lang="en",
            file_name="no_dup_baseline",
        )
        duped = summarize_run_data(
            standard_metadata(),
            self.fault_scenario_samples(duplicate=True),
            lang="en",
            file_name="dup_test",
        )
        assert_summary_sections(duped, min_findings=0)
        baseline_top = baseline.get("top_causes", [])
        duped_top = duped.get("top_causes", [])
        if baseline_top and duped_top:
            assert (
                float(duped_top[0].get("confidence", 0))
                <= float(baseline_top[0].get("confidence", 0)) + 0.15
            )
