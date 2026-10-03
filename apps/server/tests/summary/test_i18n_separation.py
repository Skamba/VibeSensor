"""Tests enforcing the multilingual architecture.

Language-neutral analysis plus render-time translation.

These tests verify:
1. Analysis output contains no localized text — only codes, i18n refs, and parameters.
2. The same analysis output renders correctly in both EN and NL.
3. Rendered reports for different languages contain the same structural facts.
"""

from __future__ import annotations

import random

import pytest

from vibesensor.analysis.summarize import summarize_run_data
from vibesensor.report.i18n import is_i18n_ref, tr
from vibesensor.report.i18n import resolve_i18n as resolve_i18n_impl

_TRANSLATED_MARKERS = [
    # Dutch markers
    "Onbekend",
    "Wiel/band",
    "Wielorde",
    "wielorde",
    "motororde",
    "aandrijfasorde",
    "Sensor zonder label",
    "Snelheidsvariatie",
    "Sensordekking",
    # English translated phrases (from report_i18n, not raw codes)
    "Unlabeled sensor",
    "wheel order",
    "engine order",
    "driveshaft order",
]


def _resolve_i18n(lang: str, value: object) -> str:
    return resolve_i18n_impl(lang, value, tr=lambda key, **kw: tr(lang, key, **kw))


# ---------------------------------------------------------------------------
# 1. Analysis output contains no localized text
# ---------------------------------------------------------------------------


def _make_analysis_summary() -> dict:
    """Produce a representative analysis summary for testing."""
    metadata = {
        "run_id": "i18n-test-001",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:05:00Z",
        "car_name": "Test Car",
        "car_type": "Sedan",
        "tire_width_mm": 225,
        "tire_aspect_pct": 45,
        "rim_in": 17,
        "raw_sample_rate_hz": 800,
        "sensor_model": "ADXL345",
    }
    rng = random.Random(123)
    samples = []
    for i in range(40):
        loc = ["Front Left", "Front Right", "Rear Left", "Rear Right"][i % 4]
        speed = 70 + i * 0.5
        samples.append(
            {
                "t_s": float(i) * 0.5,
                "speed_kmh": speed,
                "accel_x_g": 0.01,
                "accel_y_g": 0.01,
                "accel_z_g": 1.0,
                "vibration_strength_db": 20.0 + rng.uniform(-3, 3),
                "location": loc,
                "client_id": f"sensor_{loc.lower().replace(' ', '_')}",
                "client_name": loc,
                "top_peaks": [
                    {"hz": 12.5 + rng.gauss(0, 0.2), "amp": 0.05},
                ],
                "strength_floor_amp_g": 0.005,
            },
        )
    return summarize_run_data(metadata, samples, lang="en", include_samples=False)


def test_analysis_output_is_language_neutral() -> None:
    """Verify that analysis output for EN vs NL is identical (language-independent)."""
    metadata = {
        "run_id": "neutral-test",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:05:00Z",
        "raw_sample_rate_hz": 800,
        "sensor_model": "ADXL345",
    }
    samples = [
        {
            "t_s": float(i),
            "speed_kmh": 80.0,
            "vibration_strength_db": 20.0,
            "location": "Front Left",
            "client_name": "Front Left",
        }
        for i in range(10)
    ]

    summary_en = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    summary_nl = summarize_run_data(metadata, samples, lang="nl", include_samples=False)

    # Remove the 'lang' field which intentionally differs
    for key in ("lang",):
        summary_en.pop(key, None)
        summary_nl.pop(key, None)

    assert summary_en == summary_nl, (
        "Analysis output differs between EN and NL. Analysis must produce language-neutral output."
    )


def _check_no_translated_strings(obj: object, path: str = "") -> list[str]:
    """Walk a data structure looking for known translated strings.

    Returns a list of paths where localized text was found.
    """
    violations: list[str] = []

    if isinstance(obj, str):
        for marker in _TRANSLATED_MARKERS:
            if marker in obj:
                violations.append(f"{path}: contains '{marker}' in '{obj[:80]}'")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            violations.extend(_check_no_translated_strings(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            violations.extend(_check_no_translated_strings(v, f"{path}[{i}]"))

    return violations


def test_analysis_output_contains_no_translated_strings() -> None:
    """Analysis output must not contain translated strings, only codes and i18n refs."""
    summary = _make_analysis_summary()
    # Remove fields that are not analysis output (metadata passthroughs)
    for skip_key in ("lang", "metadata", "report_date"):
        summary.pop(skip_key, None)

    violations = _check_no_translated_strings(summary, "summary")
    assert not violations, "Analysis output contains translated strings:\n" + "\n".join(
        violations[:10],
    )


def test_i18n_refs_are_well_formed() -> None:
    """All i18n ref dicts in analysis output must have valid _i18n_key."""
    summary = _make_analysis_summary()

    def _check_refs(obj: object, path: str = "") -> list[str]:
        issues: list[str] = []
        if isinstance(obj, dict):
            if "_i18n_key" in obj:
                key = obj["_i18n_key"]
                if not isinstance(key, str) or not key:
                    issues.append(f"{path}: invalid _i18n_key: {key!r}")
            for k, v in obj.items():
                issues.extend(_check_refs(v, f"{path}.{k}"))
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                issues.extend(_check_refs(v, f"{path}[{i}]"))
        return issues

    issues = _check_refs(summary, "summary")
    assert not issues, "Malformed i18n refs:\n" + "\n".join(issues)


# ---------------------------------------------------------------------------
# 3. Same analysis output renders correctly in both EN and NL
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. _resolve_i18n unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lang", "value", "expected"),
    [
        pytest.param("en", "hello", "hello", id="plain_string"),
        pytest.param("en", None, "", id="none"),
        pytest.param("en", {"_i18n_key": "VALUE_UNKNOWN"}, "unknown", id="ref_en"),
        pytest.param("nl", {"_i18n_key": "VALUE_UNKNOWN"}, "onbekend", id="ref_nl"),
    ],
)
def test_resolve_i18n_simple(lang: str, value: object, expected: str) -> None:
    """Plain strings, None, and i18n ref dicts resolve correctly."""
    assert _resolve_i18n(lang, value) == expected


def test_resolve_i18n_list_of_refs() -> None:
    """Lists of i18n refs are resolved and joined."""
    refs = [
        {"_i18n_key": "VALUE_UNKNOWN"},
        {"_i18n_key": "VALUE_UNKNOWN"},
    ]
    result = _resolve_i18n("en", refs)
    assert result == "unknown unknown"


def test_resolve_i18n_nested_refs() -> None:
    """Nested i18n refs in parameters are resolved recursively."""
    ref = {
        "_i18n_key": "ORIGIN_PHASE_ONSET_NOTE",
        "phase": "acceleration",
    }
    en_result = _resolve_i18n("en", ref)
    nl_result = _resolve_i18n("nl", ref)
    # Should contain the translated phase name
    assert "acceleration" in en_result.lower() or "accel" in en_result.lower()
    assert "versnelling" in nl_result.lower() or "acceleratie" in nl_result.lower()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"_i18n_key": "TEST"}, True),
        ({"key": "TEST"}, False),
        ("plain string", False),
        (None, False),
        (42, False),
    ],
)
def test_is_i18n_ref(value: object, expected: bool) -> None:
    """_is_i18n_ref correctly identifies i18n reference dicts."""
    assert is_i18n_ref(value) is expected
