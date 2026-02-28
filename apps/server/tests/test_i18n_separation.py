# ruff: noqa: E501
"""Tests enforcing the multilingual architecture: language-neutral analysis + render-time translation.

These tests verify:
1. Analysis modules (except report_data_builder.py) do not import i18n resources.
2. Analysis output contains no localized text — only codes, i18n refs, and parameters.
3. The same analysis output renders correctly in both EN and NL.
4. Rendered reports for different languages contain the same structural facts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vibesensor.analysis import map_summary, summarize_run_data
from vibesensor.analysis.report_data_builder import _is_i18n_ref, _resolve_i18n

_SERVER_PKG = Path(__file__).resolve().parents[1] / "vibesensor"
_ANALYSIS_PKG = _SERVER_PKG / "analysis"

# Analysis modules that must NOT import from report_i18n.
# report_data_builder.py is the sole i18n bridge and is allowed.
_ANALYSIS_MODULES_NO_I18N = [
    p
    for p in _ANALYSIS_PKG.glob("*.py")
    if p.name not in ("__init__.py", "report_data_builder.py")
]


# ---------------------------------------------------------------------------
# 1. Guardrail: analysis modules cannot import i18n resources
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module_path",
    _ANALYSIS_MODULES_NO_I18N,
    ids=[p.name for p in _ANALYSIS_MODULES_NO_I18N],
)
def test_analysis_module_does_not_import_i18n(module_path: Path) -> None:
    """Analysis modules must not import from report_i18n (language resources).

    Only report_data_builder.py is allowed to access translation functions.
    This ensures analysis output remains language-neutral.
    """
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=module_path.name)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        mod = node.module
        level = node.level or 0
        full = ("." * level) + mod
        if "report_i18n" in mod:
            violations.append(f"line {node.lineno}: from {full} import ...")
    assert not violations, (
        f"{module_path.name} imports from report_i18n. "
        "Analysis modules must not use translation resources directly:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# 2. Analysis output contains no localized text
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
    import random

    random.seed(123)
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
                "vibration_strength_db": 20.0 + random.uniform(-3, 3),
                "location": loc,
                "client_id": f"sensor_{loc.lower().replace(' ', '_')}",
                "client_name": loc,
                "top_peaks": [
                    {"hz": 12.5 + random.gauss(0, 0.2), "amp": 0.05},
                ],
                "strength_floor_amp_g": 0.005,
            }
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
        "Analysis output differs between EN and NL. "
        "Analysis must produce language-neutral output."
    )


def _check_no_translated_strings(obj: object, path: str = "") -> list[str]:
    """Walk a data structure looking for known translated strings.

    Returns a list of paths where localized text was found.
    """
    # Known translated strings that should NOT appear in analysis output
    _TRANSLATED_MARKERS = [
        # Dutch markers
        "Onbekend",
        "Wiel / Band",
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
    assert not violations, (
        "Analysis output contains translated strings:\n" + "\n".join(violations[:10])
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


def test_report_renders_in_en_and_nl_from_same_analysis() -> None:
    """The same analysis output must render correctly in both EN and NL."""
    summary = _make_analysis_summary()

    summary["lang"] = "en"
    report_en = map_summary(summary)

    summary["lang"] = "nl"
    report_nl = map_summary(summary)

    # Both should produce valid report data
    assert report_en.title == "Diagnostic Worksheet"
    assert report_nl.title == "Diagnostisch werkformulier"

    # Structural equivalence: same number of sections
    assert len(report_en.next_steps) == len(report_nl.next_steps)
    assert len(report_en.data_trust) == len(report_nl.data_trust)
    assert len(report_en.system_cards) == len(report_nl.system_cards)

    # Numeric values must be identical
    assert report_en.observed.certainty_pct == report_nl.observed.certainty_pct
    assert report_en.observed.strength_peak_amp_g == report_nl.observed.strength_peak_amp_g

    # Translated content must differ
    if report_en.data_trust and report_nl.data_trust:
        assert report_en.data_trust[0].check != report_nl.data_trust[0].check


def test_data_trust_items_are_translated() -> None:
    """Data trust check labels must be translated for each language."""
    summary = _make_analysis_summary()

    summary["lang"] = "en"
    report_en = map_summary(summary)
    summary["lang"] = "nl"
    report_nl = map_summary(summary)

    en_checks = [dt.check for dt in report_en.data_trust]
    nl_checks = [dt.check for dt in report_nl.data_trust]

    # EN should have English labels
    assert any("Speed" in c or "Sensor" in c or "Frame" in c for c in en_checks)
    # NL should have Dutch labels
    assert any("Snelheid" in c or "Sensor" in c or "Frame" in c for c in nl_checks)


def test_next_steps_are_translated() -> None:
    """Next steps must be rendered in the correct language."""
    summary = _make_analysis_summary()

    summary["lang"] = "en"
    report_en = map_summary(summary)
    summary["lang"] = "nl"
    report_nl = map_summary(summary)

    if report_en.next_steps and report_nl.next_steps:
        en_action = report_en.next_steps[0].action
        nl_action = report_nl.next_steps[0].action
        # Actions should be non-empty and different (translated)
        assert en_action
        assert nl_action
        assert en_action != nl_action, (
            f"Next step not translated: EN='{en_action[:50]}' NL='{nl_action[:50]}'"
        )


# ---------------------------------------------------------------------------
# 4. _resolve_i18n unit tests
# ---------------------------------------------------------------------------


def test_resolve_i18n_plain_string() -> None:
    """Plain strings pass through unchanged."""
    assert _resolve_i18n("en", "hello") == "hello"


def test_resolve_i18n_none() -> None:
    """None resolves to empty string."""
    assert _resolve_i18n("en", None) == ""


def test_resolve_i18n_ref_dict() -> None:
    """i18n ref dicts are translated."""
    ref = {"_i18n_key": "UNKNOWN"}
    assert _resolve_i18n("en", ref) == "Unknown"
    assert _resolve_i18n("nl", ref) == "Onbekend"


def test_resolve_i18n_list_of_refs() -> None:
    """Lists of i18n refs are resolved and joined."""
    refs = [
        {"_i18n_key": "UNKNOWN"},
        {"_i18n_key": "UNKNOWN"},
    ]
    result = _resolve_i18n("en", refs)
    assert result == "Unknown Unknown"


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


def test_resolve_i18n_source_translation() -> None:
    """Source codes in params are translated at render time."""
    ref = {
        "_i18n_key": "ORIGIN_EXPLANATION_FINDING_1",
        "source": "wheel/tire",
        "speed_band": "80-100 km/h",
        "location": "Front Left",
        "dominance": "1.50x",
    }
    en_result = _resolve_i18n("en", ref)
    nl_result = _resolve_i18n("nl", ref)
    assert "Wheel / Tire" in en_result or "wheel" in en_result.lower()
    assert "Wiel / Band" in nl_result or "wiel" in nl_result.lower()


def test_is_i18n_ref() -> None:
    """_is_i18n_ref correctly identifies i18n reference dicts."""
    assert _is_i18n_ref({"_i18n_key": "TEST"})
    assert not _is_i18n_ref({"key": "TEST"})
    assert not _is_i18n_ref("plain string")
    assert not _is_i18n_ref(None)
    assert not _is_i18n_ref(42)
