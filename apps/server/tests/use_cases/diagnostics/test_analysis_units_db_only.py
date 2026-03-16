from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from _paths import SERVER_ROOT

from vibesensor.use_cases.diagnostics import summarize_run_data

_GUARDED_RAW_ROOTS = frozenset(
    {"samples", "metadata", "analysis_metadata", "_report_template_data"},
)


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
    return [
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
        for idx in range(24)
    ]


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
    return bool(path) and path[0] in _GUARDED_RAW_ROOTS


@pytest.fixture(scope="module")
def _summary() -> dict[str, Any]:
    """Run summarize_run_data once and share across the two units-policy tests."""
    return summarize_run_data(_metadata(), _samples(), lang="en", include_samples=False)


def test_post_analysis_summary_has_no_g_suffixed_output_fields(_summary: dict[str, Any]) -> None:
    offending_paths = [
        ".".join(path)
        for path, _value in _walk(_summary)
        if not _is_guarded_raw_path(path) and path and path[-1].endswith("_g")
    ]

    assert not offending_paths, (
        "Post-stop analysis output contains g-suffixed fields: "
        + ", ".join(sorted(offending_paths))
    )


def test_post_analysis_summary_has_no_g_unit_strings(_summary: dict[str, Any]) -> None:
    offending_strings = [
        f"{'.'.join(path)}={value!r}"
        for path, value in _walk(_summary)
        if not _is_guarded_raw_path(path) and isinstance(value, str) and " g" in value
    ]

    assert not offending_strings, (
        "Post-stop analysis output contains g-formatted strings: " + "; ".join(offending_strings)
    )


def test_analysis_modules_use_canonical_db_helper() -> None:
    """Analysis modules must import vibration_strength_db_scalar as canonical_vibration_db
    and call it via the alias, not directly as vibration_strength_db_scalar().
    """
    analysis_root = SERVER_ROOT / "vibesensor" / "use_cases" / "diagnostics"

    direct_users = [
        str(py_file.relative_to(analysis_root))
        for py_file in sorted(analysis_root.rglob("*.py"))
        if "vibration_strength_db_scalar(" in py_file.read_text(encoding="utf-8")
    ]

    assert not direct_users, (
        "Analysis modules must use canonical_vibration_db() (aliased import); "
        "direct vibration_strength_db_scalar() calls found in: " + ", ".join(direct_users)
    )
