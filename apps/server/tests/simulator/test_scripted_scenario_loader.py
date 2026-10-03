from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.simulator.scripted_scenario_loader import (
    ScriptedScenarioDataError,
    load_scripted_scenarios,
)


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_load_scripted_scenarios_builds_catalog_from_yaml_resources(tmp_path: Path) -> None:
    _write_yaml(tmp_path / "index.yaml", {"scenarios": ["steady-front-left"]})
    _write_yaml(
        tmp_path / "steady-front-left.yaml",
        {
            "name": "steady-front-left",
            "description": "Single synthetic scenario for loader coverage.",
            "phases": [
                {
                    "name": "hold",
                    "duration_s": 5.0,
                    "speed_start_kmh": 40.0,
                    "speed_end_kmh": 40.0,
                    "overrides": [
                        {
                            "target": "front-left",
                            "profile_name": "wheel_mild_imbalance",
                            "scene_gain": 0.8,
                            "scene_noise_gain": 1.0,
                            "amp_scale": 1.0,
                            "noise_scale": 1.02,
                        }
                    ],
                    "pulses": [{"at_s": 1.0, "target": "front-left", "strength": 0.2}],
                }
            ],
        },
    )

    scenarios = load_scripted_scenarios(resource_dir=tmp_path)

    phase = scenarios["steady-front-left"].phases[0]
    assert tuple(scenarios) == ("steady-front-left",)
    assert phase.overrides[0].profile_name == "wheel_mild_imbalance"
    assert phase.pulses[0].strength == 0.2
    assert phase.guided_phase is None


def test_bundled_guided_scenarios_mark_sweep_hold_and_neutral_coast_down() -> None:
    scenarios = load_scripted_scenarios()

    for name in ("guided-wheel-coastdown", "guided-engine-coastdown"):
        phases = scenarios[name].phases
        assert [phase.guided_phase for phase in phases] == ["sweep", "hold", "coast_down"]
        assert phases[-1].speed_end_kmh < phases[-1].speed_start_kmh
    engine_coast = scenarios["guided-engine-coastdown"].phases[-1]
    assert "engine_order" not in {override.profile_name for override in engine_coast.overrides}


def test_load_scripted_scenarios_rejects_index_name_mismatch(tmp_path: Path) -> None:
    _write_yaml(tmp_path / "index.yaml", {"scenarios": ["steady-front-left"]})
    _write_yaml(
        tmp_path / "steady-front-left.yaml",
        {
            "name": "different-name",
            "description": "Broken fixture.",
            "phases": [
                {
                    "name": "hold",
                    "duration_s": 5.0,
                    "speed_start_kmh": 40.0,
                    "speed_end_kmh": 40.0,
                    "overrides": [
                        {
                            "target": "front-left",
                            "profile_name": "wheel_mild_imbalance",
                            "scene_gain": 0.8,
                            "scene_noise_gain": 1.0,
                            "amp_scale": 1.0,
                            "noise_scale": 1.02,
                        }
                    ],
                }
            ],
        },
    )

    with pytest.raises(ScriptedScenarioDataError, match="must declare name 'steady-front-left'"):
        load_scripted_scenarios(resource_dir=tmp_path)
