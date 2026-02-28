from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from vibesensor.analysis.summary import summarize_run_data


def _metadata() -> dict[str, Any]:
    return {
        "run_id": "unit-guard-run",
        "language": "en",
        "raw_sample_rate_hz": 400.0,
        "tire_circumference_m": 2.1,
        "final_drive_ratio": 3.7,
        "current_gear_ratio": 0.8,
    }


def _samples() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx in range(24):
        rows.append(
            {
                "t_s": float(idx) * 0.25,
                "speed_kmh": 70.0 + (idx % 6),
                "accel_x_g": 0.02,
                "accel_y_g": 0.015,
                "accel_z_g": 0.01,
                "vibration_strength_db": 22.0 + (idx % 5),
                "dominant_freq_hz": 30.0,
                "top_peaks": [
                    {"hz": 30.0, "amp": 0.08},
                    {"hz": 60.0, "amp": 0.03},
                    {"hz": 90.0, "amp": 0.02},
                ],
                "client_name": "rear-left wheel",
                "strength_floor_amp_g": 0.01,
            }
        )
    return rows


def _walk(node: Any, *, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            key_text = str(key)
            next_path = (*path, key_text)
            yield (next_path, value)
            yield from _walk(value, path=next_path)
        return
    if isinstance(node, list):
        for idx, item in enumerate(node):
            next_path = (*path, f"[{idx}]")
            yield (next_path, item)
            yield from _walk(item, path=next_path)


def _is_guarded_raw_path(path: tuple[str, ...]) -> bool:
    if not path:
        return False
    return path[0] in {"samples", "metadata", "analysis_metadata", "_report_template_data"}


def test_post_analysis_summary_has_no_g_suffixed_output_fields() -> None:
    metadata = _metadata()
    samples = _samples()
    summary = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    offending_paths: list[str] = []
    for path, _value in _walk(summary):
        if _is_guarded_raw_path(path):
            continue
        if path and path[-1].endswith("_g"):
            offending_paths.append(".".join(path))

    assert not offending_paths, (
        "Post-stop analysis output contains g-suffixed fields: "
        + ", ".join(sorted(offending_paths))
    )


def test_post_analysis_summary_has_no_g_unit_strings() -> None:
    metadata = _metadata()
    samples = _samples()
    summary = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    offending_strings: list[str] = []
    for path, value in _walk(summary):
        if _is_guarded_raw_path(path):
            continue
        if isinstance(value, str) and " g" in value:
            offending_strings.append(f"{'.'.join(path)}={value!r}")

    assert not offending_strings, (
        "Post-stop analysis output contains g-formatted strings: " + "; ".join(offending_strings)
    )


def test_analysis_modules_use_canonical_db_helper() -> None:
    analysis_root = Path(__file__).resolve().parents[1] / "vibesensor" / "analysis"
    canonical_module = analysis_root / "db_units.py"
    assert canonical_module.exists()

    direct_users: list[str] = []
    for py_file in sorted(analysis_root.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        if "vibration_strength_db_scalar(" in text and py_file.name != "db_units.py":
            direct_users.append(str(py_file.relative_to(analysis_root)))

    assert not direct_users, (
        "Analysis modules must use canonical_vibration_db() from db_units.py; "
        "direct vibration_strength_db_scalar() calls found in: " + ", ".join(direct_users)
    )
