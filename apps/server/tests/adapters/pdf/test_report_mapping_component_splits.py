from __future__ import annotations

from vibesensor.adapters.pdf.mapping import (
    _resolve_optional_step_value,
    collect_location_intensity,
    peak_row_system_label,
    tire_spec_text,
)


def test_resolve_optional_step_value_returns_none_for_empty_text() -> None:
    def tr(key: str, **_kw: object) -> str:
        return key

    assert _resolve_optional_step_value("", lang="en", tr=tr) is None


def test_collect_location_intensity_prefers_p95_then_mean() -> None:
    assert collect_location_intensity(
        [
            {"location": "Front Left", "p95_intensity_db": 20.0},
            {"location": "Front Left", "mean_intensity_db": 18.0},
        ],
    ) == {"Front Left": [20.0, 18.0]}


def test_peak_row_system_label_from_suspected_source() -> None:
    def tr(key: str, **_kw: object) -> str:
        return key

    assert peak_row_system_label({"suspected_source": "wheel/tire"}, tr=tr) == "SOURCE_WHEEL_TIRE"
    assert peak_row_system_label({"suspected_source": "engine"}, tr=tr) == "SOURCE_ENGINE"
    assert peak_row_system_label({"suspected_source": "driveline"}, tr=tr) == "SOURCE_DRIVELINE"
    assert (
        peak_row_system_label({"suspected_source": "transient_impact"}, tr=tr)
        == "SOURCE_TRANSIENT_IMPACT"
    )
    assert peak_row_system_label({"suspected_source": ""}, tr=tr) == "\u2014"
    assert peak_row_system_label({}, tr=tr) == "\u2014"


def test_tire_spec_text_requires_complete_positive_dimensions() -> None:
    assert (
        tire_spec_text({"tire_width_mm": 225, "tire_aspect_pct": 45, "rim_in": 17}) == "225/45R17"
    )
    assert tire_spec_text({"tire_width_mm": 225, "rim_in": 17}) is None
