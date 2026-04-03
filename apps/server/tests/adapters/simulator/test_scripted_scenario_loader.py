from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.adapters.simulator.scripted_scenario_loader import (
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
                            "common_event_gain": 0.16,
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
                            "common_event_gain": 0.16,
                        }
                    ],
                }
            ],
        },
    )

    with pytest.raises(ScriptedScenarioDataError, match="must declare name 'steady-front-left'"):
        load_scripted_scenarios(resource_dir=tmp_path)
