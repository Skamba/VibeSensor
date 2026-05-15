from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TOOLS_DEV = _REPO_ROOT / "tools" / "dev"


def _load_tool_module(name: str) -> ModuleType:
    module_path = _TOOLS_DEV / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_test_module", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_processing_fuzz_assertions_are_testable_without_cli() -> None:
    module = _load_tool_module("fuzz_processing_assertions")

    assert module.is_sorted_desc([3.0, 2.0, 2.0, 1.0])
    assert not module.is_sorted_desc([1.0, 3.0])
    module.json_no_nan({"value": 1.0})
    module.json_no_nan({"nested": [{"value": 1.0}]})
    with pytest.raises(ValueError):
        module.json_no_nan({"value": float("nan")})


def test_analysis_summary_assertions_are_testable_without_cli() -> None:
    module = _load_tool_module("fuzz_analysis_assertions")
    validated: list[object] = []

    class _TypeAdapter:
        def __init__(self, schema: object) -> None:
            self.schema = schema

        def validate_python(self, value: object) -> object:
            validated.append((self.schema, value))
            return value

    module.validate_summary(
        {"rows": 2, "findings": [], "run_suitability": {}},
        expected_rows=2,
        TypeAdapter=_TypeAdapter,
        AnalysisSummary=object,
    )

    assert validated
    assert validated[0][1]["rows"] == 2
    with pytest.raises(AssertionError, match="summary findings missing"):
        module.validate_summary(
            {"rows": 2, "run_suitability": {}},
            expected_rows=2,
            TypeAdapter=_TypeAdapter,
            AnalysisSummary=object,
        )


def test_analysis_scenario_materializer_is_testable_without_cli() -> None:
    module = _load_tool_module("fuzz_analysis_scenarios")

    class _AnalysisSettingsSnapshot:
        @classmethod
        def from_dict(cls, metadata: dict[str, object]) -> dict[str, object]:
            return metadata

    def _vehicle_orders_hz(*, speed_mps: float, settings: object) -> dict[str, float]:
        return {"wheel_hz": speed_mps}

    samples = module.materialize_samples(
        {
            "metadata": {
                "run_id": "fuzz-test",
                "raw_sample_rate_hz": 800,
                "current_gear_ratio": 1.0,
                "final_drive_ratio": 4.0,
            },
            "sensors": [
                {
                    "client_id": "fl-wheel",
                    "client_name": "Front Left Wheel",
                    "location": "front_left_wheel",
                }
            ],
            "scenario": "steady",
            "fault_kind": "wheel",
            "steps": 1,
            "dt_s": 1.0,
            "low_speed": 36.0,
            "high_speed": 72.0,
            "floor_amp_g": 0.01,
            "base_fault_amp_g": 0.1,
            "diffuse_excitation": False,
            "missing_speed_ratio": 0.0,
            "blank_location_ratio": 0.0,
            "drop_counter": 0,
            "overflow_counter": 0,
            "accel_scale": 0.02,
            "background_hz": 20.0,
            "clutter_hz": 40.0,
        },
        vibration_strength_db_scalar=lambda *, peak_band_rms_amp_g, floor_amp_g: (
            peak_band_rms_amp_g / floor_amp_g
        ),
        bucket_for_strength=lambda value: "l1" if value > 1.0 else "l0",
        AnalysisSettingsSnapshot=_AnalysisSettingsSnapshot,
        vehicle_orders_hz=_vehicle_orders_hz,
    )

    assert len(samples) == 1
    assert samples[0]["run_id"] == "fuzz-test"
    assert samples[0]["sample_rate_hz"] == 800
    assert samples[0]["strength_bucket"] == "l1"
    assert json.dumps(samples, allow_nan=False)


def test_common_worker_helpers_are_testable_without_cli() -> None:
    module = _load_tool_module("fuzz_common")

    assert module.worker_seed(None, 3) is None
    assert module.worker_seed(100, 3) == 103
    assert module.worker_prefix(None) == ""
    assert module.worker_prefix(2) == "[worker 2] "
    assert module.worker_prefix(0) == "[worker 0] "


def test_fuzz_artifact_writers_are_testable_without_cli(tmp_path: Path) -> None:
    module = _load_tool_module("fuzz_artifacts")

    processing_path = module.write_processing_failure_artifact(
        target="fft",
        case={"value": 1.0},
        output={"ok": False},
        exc=RuntimeError("boom"),
        artifact_dir=tmp_path,
    )
    assert processing_path is not None
    processing_payload = json.loads(processing_path.read_text(encoding="utf-8"))
    assert processing_payload["target"] == "fft"
    assert processing_payload["case"] == {"value": 1.0}
    assert processing_payload["output"] == {"ok": False}
    assert processing_payload["exception_type"] == "RuntimeError"
    assert processing_payload["exception_message"] == "boom"

    analysis_path = module.write_analysis_failure_artifact(
        case={"metadata": {"run_id": "fuzz-run"}, "samples": []},
        summary={"rows": 0},
        exc=ValueError("bad"),
        artifact_dir=tmp_path,
    )
    assert analysis_path is not None
    assert analysis_path.name.endswith("-fuzz-run.json")
    analysis_payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    assert analysis_payload["summary"] == {"rows": 0}
    assert analysis_payload["exception_type"] == "ValueError"
    assert analysis_payload["exception_message"] == "bad"
