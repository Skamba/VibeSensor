"""Direct behavior tests for diffuse excitation detection."""

from __future__ import annotations

from typing import Any

from test_support import make_sample as _make_sample
from test_support import make_speed_sweep_fault_samples as _make_speed_sweep_fault_samples
from test_support import standard_metadata as _standard_metadata
from test_support import wheel_hz as _wheel_hz

from vibesensor.adapters.analysis_summary import build_findings_for_samples
from vibesensor.domain import OrderMatchObservation
from vibesensor.use_cases.diagnostics.orders.heuristics import (
    detect_diffuse_excitation as _detect_diffuse_excitation,
)


class TestDetectDiffuseExcitation:
    """Direct unit tests for _detect_diffuse_excitation."""

    def test_single_sensor_returns_not_diffuse(self) -> None:
        is_diff, penalty = _detect_diffuse_excitation(
            connected_locations={"front_left"},
            possible_by_location={"front_left": 20},
            matched_by_location={"front_left": 15},
            matched_points=[
                OrderMatchObservation(
                    predicted_hz=50.0,
                    matched_hz=50.5,
                    rel_error=0.01,
                    amp=0.1,
                    location="front_left",
                )
            ]
            * 15,
        )
        assert not is_diff
        assert penalty == 1.0

    def test_uniform_rates_uniform_amplitude_is_diffuse(self) -> None:
        locs = {"front_left", "front_right", "rear"}
        possible = dict.fromkeys(locs, 30)
        matched = dict.fromkeys(locs, 20)
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location=loc,
            )
            for loc in locs
            for _ in range(20)
        ]
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert is_diff, "Uniform rates + uniform amplitude should be diffuse"
        assert penalty < 1.0

    def test_dominant_amplitude_is_not_diffuse(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 20, "rear": 20}
        matched = {"front_left": 15, "rear": 14}
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.30,
                location="front_left",
            )
        ] * 15 + [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="rear",
            ),
        ] * 14
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Strong amplitude dominance should NOT be diffuse"

    def test_insufficient_samples_per_location(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 2, "rear": 2}
        matched = {"front_left": 2, "rear": 2}
        pts = [
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.05,
                location="front_left",
            )
        ] * 2
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Too few samples should not trigger diffuse"

    def test_empty_matched_points(self) -> None:
        locs = {"a", "b"}
        is_diff, penalty = _detect_diffuse_excitation(
            locs,
            {"a": 20, "b": 20},
            {"a": 15, "b": 15},
            [],
        )
        assert isinstance(is_diff, bool)
        assert penalty <= 1.0


def _wheel_findings(findings: tuple | list, *, exclude_ref: bool = False) -> list:
    return [
        f
        for f in findings
        if (not exclude_ref or not f.finding_id.startswith("REF_"))
        and f.finding_key.startswith("wheel_")
    ]


class TestDiffuseExcitationFindingFlags:
    def test_uniform_peaks_all_sensors_flags_diffuse(self) -> None:
        sensors = ["front-left", "front-right", "rear-left", "rear-right"]
        samples: list[dict[str, Any]] = []
        for i in range(40):
            speed = 50.0 + i * 1.5
            whz = _wheel_hz(speed)
            for sensor in sensors:
                samples.append(
                    _make_sample(
                        t_s=float(i),
                        speed_kmh=speed,
                        client_name=sensor,
                        top_peaks=[
                            {"hz": whz, "amp": 0.05},
                            {"hz": whz * 2, "amp": 0.02},
                        ],
                        vibration_strength_db=24.0,
                    ),
                )

        findings = build_findings_for_samples(
            metadata=_standard_metadata(),
            samples=samples,
            lang="en",
        )

        for finding in _wheel_findings(findings, exclude_ref=True):
            assert finding.diffuse_excitation is True, (
                f"Expected diffuse excitation flag for {finding.finding_key}"
            )

    def test_single_sensor_fault_not_flagged_diffuse(self) -> None:
        samples = _make_speed_sweep_fault_samples(
            fault_sensor="front-right",
            sensors=["front-left", "front-right", "rear-left", "rear-right"],
            speed_start=50.0,
            speed_end=108.5,
            n_steps=40,
            samples_per_step=1,
            fault_amp=0.08,
            noise_amp=0.005,
            fault_vib_db=28.0,
            noise_vib_db=10.0,
        )
        findings = build_findings_for_samples(
            metadata=_standard_metadata(),
            samples=samples,
            lang="en",
        )

        for finding in _wheel_findings(findings, exclude_ref=True):
            assert finding.diffuse_excitation is not True
