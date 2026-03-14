from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_support import (
    make_diffuse_samples,
    make_engine_order_samples,
    make_sample,
    standard_metadata,
)
from test_support.scenario_ground_truth import ALL_SENSORS, fault_phase

from vibesensor.analysis import RunAnalysis, summarize_run_data
from vibesensor.analysis_settings import wheel_hz_from_speed_kmh
from vibesensor.boundaries.diagnostic_case import project_summary_through_domain
from vibesensor.history_db import HistoryDB


def _run_suitability_state(summary: dict[str, Any], check_key: str) -> str | None:
    suitability = summary.get("run_suitability")
    if not isinstance(suitability, list):
        return None
    for check in suitability:
        if not isinstance(check, dict):
            continue
        if check.get("check_key") == check_key:
            state = check.get("state")
            return str(state) if state is not None else None
    return None


def _top_cause(summary: dict[str, Any]) -> dict[str, Any] | None:
    top_causes = summary.get("top_causes")
    if not isinstance(top_causes, list) or not top_causes:
        return None
    top_cause = top_causes[0]
    return top_cause if isinstance(top_cause, dict) else None


def _first_action_id(summary: dict[str, Any]) -> str | None:
    test_plan = summary.get("test_plan")
    if not isinstance(test_plan, list) or not test_plan:
        return None
    first = test_plan[0]
    if not isinstance(first, dict):
        return None
    action_id = first.get("action_id")
    return str(action_id) if action_id is not None else None


def _action_ids(summary: dict[str, Any]) -> list[str]:
    test_plan = summary.get("test_plan")
    if not isinstance(test_plan, list):
        return []

    action_ids: list[str] = []
    for step in test_plan:
        if not isinstance(step, dict):
            continue
        action_id = step.get("action_id")
        if action_id is None:
            continue
        action_ids.append(str(action_id))
    return action_ids


def _persist_and_reload_summary(tmp_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    db = HistoryDB(tmp_path / "history.db")
    run: dict[str, Any] | None = None
    try:
        db.create_run(
            "characterization-roundtrip",
            "2026-01-01T00:00:00Z",
            standard_metadata(),
        )
        db.finalize_run("characterization-roundtrip", "2026-01-01T00:01:00Z")
        db.store_analysis("characterization-roundtrip", summary)
        run = db.get_run("characterization-roundtrip")
    finally:
        db.close()

    assert run is not None
    analysis = run.get("analysis")
    assert isinstance(analysis, dict)
    return project_summary_through_domain(analysis)


def _driveline_samples() -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for idx in range(24):
        speed_kmh = 55.0 + (2.0 * idx)
        wheel_hz = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        samples.append(
            make_sample(
                t_s=float(idx),
                speed_kmh=speed_kmh,
                client_name="front-right",
                top_peaks=[{"hz": wheel_hz * 3.08 * 2.0, "amp": 0.04}],
                vibration_strength_db=20.0,
                strength_floor_amp_g=0.002,
            )
        )
    return samples


def _short_run_samples() -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for idx in range(5):
        for sensor in ALL_SENSORS:
            if sensor == "front-right":
                peaks = [{"hz": 11.0, "amp": 0.06}]
                vibration_db = 26.0
            else:
                peaks = [{"hz": 142.5, "amp": 0.003}]
                vibration_db = 8.0
            samples.append(
                make_sample(
                    t_s=float(idx),
                    speed_kmh=80.0,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=vibration_db,
                    strength_floor_amp_g=0.003,
                )
            )
    return samples


def test_characterization_wheel_fault_summary_contract() -> None:
    analysis = RunAnalysis(
        standard_metadata(),
        fault_phase(
            speed_kmh=80.0,
            duration_s=20.0,
            fault_sensor="front-right",
            sensors=ALL_SENSORS,
        ),
        lang="en",
        file_name="characterization-wheel",
    )
    summary = analysis.summarize()

    top_cause = _top_cause(summary)
    origin = summary["most_likely_origin"]
    test_run = analysis.test_run

    assert top_cause is not None
    assert test_run is not None
    assert top_cause["finding_key"] == "wheel_1x"
    assert top_cause["suspected_source"] == "wheel/tire"
    assert top_cause["confidence"] == pytest.approx(0.5028523562048559)
    assert top_cause["confidence_tone"] == "warn"
    assert top_cause["strongest_speed_band"] == "80-90 km/h"
    assert test_run.hypotheses[0].hypothesis_id == "hyp-1x_wheel"
    assert test_run.hypotheses[0].is_supported is True
    assert origin["location"] == "front-right"
    assert origin["alternative_locations"] == ["front-left"]
    assert origin["suspected_source"] == "wheel/tire"
    assert origin["weak_spatial_separation"] is False
    assert origin["dominant_phase"] is None
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SPEED_VARIATION") == "warn"
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SENSOR_COVERAGE") == "pass"
    assert _first_action_id(summary) == "wheel_tire_condition"


def test_characterization_live_analysis_surfaces_domain_plan_ordering() -> None:
    analysis = RunAnalysis(
        standard_metadata(),
        fault_phase(
            speed_kmh=80.0,
            duration_s=20.0,
            fault_sensor="front-right",
            sensors=ALL_SENSORS,
        ),
        lang="en",
        file_name="characterization-wheel-planning",
    )

    summary = analysis.summarize()
    test_run = analysis.test_run

    assert test_run is not None
    action_ids = [action.action_id for action in test_run.test_plan.prioritized_actions]
    assert action_ids[:2] == [
        "wheel_tire_condition",
        "wheel_balance_and_runout",
    ]
    assert test_run.test_plan.needs_more_data() is False
    assert _action_ids(summary)[:2] == [
        "wheel_tire_condition",
        "wheel_balance_and_runout",
    ]


def test_characterization_wheel_fault_persist_reload_round_trip(tmp_path: Path) -> None:
    analysis = RunAnalysis(
        standard_metadata(),
        fault_phase(
            speed_kmh=80.0,
            duration_s=20.0,
            fault_sensor="front-right",
            sensors=ALL_SENSORS,
        ),
        lang="en",
        file_name="characterization-wheel-roundtrip",
    )

    round_trip_summary = _persist_and_reload_summary(tmp_path, analysis.summarize())
    top_cause = _top_cause(round_trip_summary)
    origin = round_trip_summary["most_likely_origin"]

    assert top_cause is not None
    assert top_cause["finding_key"] == "wheel_1x"
    assert top_cause["suspected_source"] == "wheel/tire"
    assert top_cause["confidence"] == pytest.approx(0.5028523562048559)
    assert origin["location"] == "Front-Right"
    assert origin["alternative_locations"] == []
    assert origin["suspected_source"] == "wheel/tire"
    assert origin["weak_spatial_separation"] is False
    assert _run_suitability_state(round_trip_summary, "SUITABILITY_CHECK_SENSOR_COVERAGE") == "pass"
    assert _first_action_id(round_trip_summary) == "wheel_tire_condition"


def test_characterization_driveline_summary_contract() -> None:
    summary = summarize_run_data(
        standard_metadata(),
        _driveline_samples(),
        lang="en",
        file_name="characterization-driveline",
    )

    top_cause = _top_cause(summary)
    origin = summary["most_likely_origin"]

    assert top_cause is not None
    assert top_cause["finding_key"] == "driveshaft_2x"
    assert top_cause["suspected_source"] == "driveline"
    assert top_cause["confidence"] == pytest.approx(0.45373427721763776)
    assert top_cause["confidence_tone"] == "warn"
    assert top_cause["strongest_speed_band"] == "90-100 km/h"
    assert origin["location"] == "front-right"
    assert origin["alternative_locations"] == []
    assert origin["suspected_source"] == "driveline"
    assert origin["weak_spatial_separation"] is True
    assert origin["dominant_phase"] == "acceleration"
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SPEED_VARIATION") == "pass"
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SENSOR_COVERAGE") == "warn"
    assert _first_action_id(summary) == "driveline_mounts_and_fasteners"


def test_characterization_engine_order_currently_falls_back_to_baseline_noise() -> None:
    summary = summarize_run_data(
        standard_metadata(),
        make_engine_order_samples(sensors=ALL_SENSORS, speed_kmh=80.0, n_samples=30),
        lang="en",
        file_name="characterization-engine-order",
    )

    origin = summary["most_likely_origin"]

    assert summary["top_causes"] == []
    assert origin["location"] == "unknown"
    assert origin["alternative_locations"] == []
    assert origin["suspected_source"] == "baseline_noise"
    assert origin["weak_spatial_separation"] is False
    assert origin["dominant_phase"] is None
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SPEED_VARIATION") == "warn"
    assert _first_action_id(summary) == "general_mechanical_inspection"


def test_characterization_diffuse_uniform_excitation_stays_unlocalized() -> None:
    summary = summarize_run_data(
        standard_metadata(),
        make_diffuse_samples(
            sensors=ALL_SENSORS,
            speed_kmh=80.0,
            n_samples=30,
            amp=0.01,
            vib_db=12.0,
            freq_hz=11.0,
        ),
        lang="en",
        file_name="characterization-diffuse",
    )

    origin = summary["most_likely_origin"]

    assert summary["top_causes"] == []
    assert origin["location"] == "unknown"
    assert origin["alternative_locations"] == []
    assert origin["suspected_source"] == "baseline_noise"
    assert origin["weak_spatial_separation"] is False
    assert origin["dominant_phase"] is None
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SPEED_VARIATION") == "warn"
    assert _first_action_id(summary) == "general_mechanical_inspection"


def test_characterization_short_run_contract() -> None:
    summary = summarize_run_data(
        standard_metadata(),
        _short_run_samples(),
        lang="en",
        file_name="characterization-short-run",
    )

    top_cause = _top_cause(summary)
    origin = summary["most_likely_origin"]

    assert top_cause is not None
    assert top_cause["finding_key"] == "peak_11hz"
    assert top_cause["suspected_source"] == "unknown_resonance"
    assert top_cause["confidence"] == pytest.approx(0.735)
    assert top_cause["confidence_tone"] == "success"
    assert top_cause["strongest_speed_band"] == "80-90 km/h"
    assert origin["location"] == "unknown"
    assert origin["alternative_locations"] == []
    assert origin["suspected_source"] == "unknown_resonance"
    assert origin["weak_spatial_separation"] is False
    assert origin["dominant_phase"] is None
    assert _run_suitability_state(summary, "SUITABILITY_CHECK_SPEED_VARIATION") == "warn"
    assert _first_action_id(summary) == "general_mechanical_inspection"