from __future__ import annotations

from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

import yaml
from pydantic import ConfigDict, TypeAdapter, ValidationError

from vibesensor.adapters.simulator.scripted_scenario_models import (
    PhaseOverride,
    PhasePulse,
    ScenarioPhase,
    ScriptedScenario,
)
from vibesensor.shared._data_files import resolve_static_data_file

__all__ = ["ScriptedScenarioDataError", "load_scripted_scenarios"]

_RESOURCE_SUBDIR = "scripted_scenarios"
_INDEX_FILE_NAME = "index.yaml"
_STRICT_TYPEDDICT_CONFIG = ConfigDict(extra="forbid")


class ScriptedScenarioIndexPayload(TypedDict):
    scenarios: list[str]


class PhaseOverridePayload(TypedDict):
    target: str
    profile_name: str
    scene_gain: float
    scene_noise_gain: float
    amp_scale: float
    noise_scale: float
    common_event_gain: float


class PhasePulsePayload(TypedDict):
    at_s: float
    target: str
    strength: float


class ScenarioPhasePayload(TypedDict):
    name: str
    duration_s: float
    speed_start_kmh: float
    speed_end_kmh: float
    overrides: list[PhaseOverridePayload]
    pulses: NotRequired[list[PhasePulsePayload]]


class ScriptedScenarioPayload(TypedDict):
    name: str
    description: str
    phases: list[ScenarioPhasePayload]


for _typed_dict in (
    ScriptedScenarioIndexPayload,
    PhaseOverridePayload,
    PhasePulsePayload,
    ScenarioPhasePayload,
    ScriptedScenarioPayload,
):
    cast(Any, _typed_dict).__pydantic_config__ = _STRICT_TYPEDDICT_CONFIG

_INDEX_ADAPTER = TypeAdapter(ScriptedScenarioIndexPayload)
_SCENARIO_ADAPTER = TypeAdapter(ScriptedScenarioPayload)


class ScriptedScenarioDataError(RuntimeError):
    """Raised when bundled scripted-scenario artifacts are missing or invalid."""


def _scenario_resource_dir(resource_dir: Path | None) -> Path:
    if resource_dir is not None:
        return resource_dir
    return resolve_static_data_file(f"{_RESOURCE_SUBDIR}/{_INDEX_FILE_NAME}").parent


def _load_yaml(path: Path) -> object:
    try:
        with path.open(encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (FileNotFoundError, PermissionError, OSError, yaml.YAMLError) as exc:
        raise ScriptedScenarioDataError(
            f"Could not load scripted scenario resource {path}: {exc}"
        ) from exc


def _load_index(resource_dir: Path) -> tuple[str, ...]:
    path = resource_dir / _INDEX_FILE_NAME
    try:
        payload = _INDEX_ADAPTER.validate_python(_load_yaml(path))
    except ValidationError as exc:
        raise ScriptedScenarioDataError(f"Invalid scripted scenario index {path}: {exc}") from exc
    names = tuple(name.strip() for name in payload["scenarios"] if name.strip())
    if not names:
        raise ScriptedScenarioDataError(f"Scripted scenario index {path} is empty")
    if len(set(names)) != len(names):
        raise ScriptedScenarioDataError(f"Scripted scenario index {path} contains duplicates")
    return names


def _phase_override_from_payload(payload: PhaseOverridePayload) -> PhaseOverride:
    return PhaseOverride(
        target=payload["target"],
        profile_name=payload["profile_name"],
        scene_gain=payload["scene_gain"],
        scene_noise_gain=payload["scene_noise_gain"],
        amp_scale=payload["amp_scale"],
        noise_scale=payload["noise_scale"],
        common_event_gain=payload["common_event_gain"],
    )


def _phase_pulse_from_payload(payload: PhasePulsePayload) -> PhasePulse:
    return PhasePulse(
        at_s=payload["at_s"],
        target=payload["target"],
        strength=payload["strength"],
    )


def _phase_from_payload(
    payload: ScenarioPhasePayload, *, scenario_name: str, path: Path
) -> ScenarioPhase:
    overrides = tuple(_phase_override_from_payload(item) for item in payload["overrides"])
    if not overrides:
        raise ScriptedScenarioDataError(
            f"Scenario {scenario_name!r} in {path} contains a phase without overrides"
        )
    return ScenarioPhase(
        name=payload["name"],
        duration_s=payload["duration_s"],
        speed_start_kmh=payload["speed_start_kmh"],
        speed_end_kmh=payload["speed_end_kmh"],
        overrides=overrides,
        pulses=tuple(_phase_pulse_from_payload(item) for item in payload.get("pulses", [])),
    )


def _scenario_from_path(path: Path) -> ScriptedScenario:
    try:
        payload = _SCENARIO_ADAPTER.validate_python(_load_yaml(path))
    except ValidationError as exc:
        raise ScriptedScenarioDataError(f"Invalid scripted scenario file {path}: {exc}") from exc
    if payload["name"] != path.stem:
        raise ScriptedScenarioDataError(
            f"Scenario file {path} must declare name {path.stem!r}, got {payload['name']!r}"
        )
    phases = tuple(
        _phase_from_payload(phase_payload, scenario_name=payload["name"], path=path)
        for phase_payload in payload["phases"]
    )
    if not phases:
        raise ScriptedScenarioDataError(f"Scenario {payload['name']!r} in {path} has no phases")
    return ScriptedScenario(
        name=payload["name"],
        description=payload["description"],
        phases=phases,
    )


def load_scripted_scenarios(resource_dir: Path | None = None) -> dict[str, ScriptedScenario]:
    resolved_resource_dir = _scenario_resource_dir(resource_dir)
    scenarios: dict[str, ScriptedScenario] = {}
    for scenario_name in _load_index(resolved_resource_dir):
        scenario = _scenario_from_path(resolved_resource_dir / f"{scenario_name}.yaml")
        scenarios[scenario.name] = scenario
    return scenarios
