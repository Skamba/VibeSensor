from __future__ import annotations

import pytest
from test_support.report_analysis_integration import max_non_ref_confidence, wheel_metadata
from test_support.report_helpers import analysis_sample as _make_sample

from vibesensor.analysis import build_findings_for_samples
from vibesensor.analysis import findings_order_findings as order_findings_module
from vibesensor.analysis.summary_payload import summarize_origin
from vibesensor.analysis.test_plan import _location_speedbin_summary
from vibesensor.analysis_settings import wheel_hz_from_speed_kmh


def test_location_speedbin_summary_reports_ambiguous_location_for_near_tie() -> None:
    matches = [
        {"speed_kmh": 85.0, "amp": 0.0110, "location": "Rear Right"},
        {"speed_kmh": 85.0, "amp": 0.0102, "location": "Rear Left"},
        {"speed_kmh": 86.0, "amp": 0.0112, "location": "Rear Right"},
        {"speed_kmh": 86.0, "amp": 0.0103, "location": "Rear Left"},
    ]

    sentence, hotspot = _location_speedbin_summary(matches, lang="en")

    assert hotspot is not None
    assert bool(hotspot.get("ambiguous_location"))
    assert hotspot.get("location") == "ambiguous location: Rear Right / Rear Left"
    assert hotspot.get("ambiguous_locations") == ["Rear Right", "Rear Left"]
    assert float(hotspot.get("localization_confidence") or 0.0) < 0.4
    assert isinstance(sentence, dict)
    assert sentence.get("_i18n_key") == "STRONGEST_AT_LOCATION_IN_SPEED_RANGE"
    assert "ambiguous location" in str(sentence.get("location", ""))


def test_location_speedbin_summary_weak_spatial_threshold_adapts_to_location_count() -> None:
    base_matches = [
        {"speed_kmh": 85.0, "amp": 1.30, "location": "Front Left"},
        {"speed_kmh": 85.0, "amp": 1.00, "location": "Front Right"},
    ]

    _, hotspot_2 = _location_speedbin_summary(base_matches, lang="en")
    assert hotspot_2 is not None
    assert hotspot_2.get("weak_spatial_separation") is False

    _, hotspot_3 = _location_speedbin_summary(
        base_matches + [{"speed_kmh": 85.0, "amp": 0.40, "location": "Rear Left"}],
        lang="en",
    )
    assert hotspot_3 is not None
    assert hotspot_3.get("weak_spatial_separation") is True

    _, hotspot_4 = _location_speedbin_summary(
        base_matches
        + [
            {"speed_kmh": 85.0, "amp": 0.40, "location": "Rear Left"},
            {"speed_kmh": 85.0, "amp": 0.35, "location": "Rear Right"},
        ],
        lang="en",
    )
    assert hotspot_4 is not None
    assert hotspot_4.get("weak_spatial_separation") is True


def test_most_likely_origin_summary_uses_adaptive_weak_spatial_fallback() -> None:
    origin = summarize_origin(
        [
            {
                "suspected_source": "wheel/tire",
                "strongest_location": "Front Left",
                "strongest_speed_band": "80-90 km/h",
                "dominance_ratio": 1.30,
                "weak_spatial_separation": False,
                "location_hotspot": {"location_count": 3},
                "confidence_0_to_1": 0.8,
            },
        ],
    )
    assert origin["weak_spatial_separation"] is True


def test_location_speedbin_summary_can_restrict_to_relevant_speed_bins() -> None:
    matches = [
        {"speed_kmh": 65.0, "amp": 0.030, "location": "Rear Left"},
        {"speed_kmh": 66.0, "amp": 0.028, "location": "Rear Left"},
        {"speed_kmh": 105.0, "amp": 0.019, "location": "Front Right"},
        {"speed_kmh": 106.0, "amp": 0.020, "location": "Front Right"},
    ]

    _, unconstrained = _location_speedbin_summary(matches, lang="en")
    _, focused = _location_speedbin_summary(
        matches,
        lang="en",
        relevant_speed_bins=["100-110 km/h"],
    )

    assert unconstrained is not None
    assert focused is not None
    assert unconstrained.get("location") == "Rear Left"
    assert focused.get("location") == "Front Right"
    focused_range = str(focused.get("speed_range") or "")
    low_text, high_text = focused_range.replace(" km/h", "").split("-", maxsplit=1)
    assert float(low_text) >= 100.0
    assert float(high_text) <= 110.0


def test_location_speedbin_summary_reports_weighted_boundary_straddling_window() -> None:
    matches = [
        {"speed_kmh": 74.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 75.0, "amp": 0.005, "location": "Front Left"},
        {"speed_kmh": 76.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 77.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 78.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 79.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 80.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 81.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 82.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 83.0, "amp": 0.030, "location": "Front Left"},
        {"speed_kmh": 84.0, "amp": 0.005, "location": "Front Left"},
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")
    assert hotspot is not None
    speed_range = str(hotspot.get("speed_range") or "")
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 75.0 <= low <= 77.0
    assert 83.0 <= high <= 85.0
    assert speed_range not in {"70-80 km/h", "80-90 km/h"}


def test_location_speedbin_summary_prefers_better_sample_coverage_over_tiny_outlier_bin() -> None:
    sparse_loud_bin = [
        {"speed_kmh": 85.0, "amp": 0.120, "location": "Rear Left"},
        {"speed_kmh": 86.0, "amp": 0.120, "location": "Rear Left"},
    ]
    dense_moderate_bin = [
        {"speed_kmh": 95.0 + (0.1 * idx), "amp": 0.090, "location": "Front Left"}
        for idx in range(20)
    ]

    _, hotspot = _location_speedbin_summary(sparse_loud_bin + dense_moderate_bin, lang="en")
    assert hotspot is not None
    assert hotspot.get("location") == "Front Left"
    speed_range = str(hotspot.get("speed_range") or "")
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 95.0 <= low <= high <= 97.0


def test_location_speedbin_summary_prefers_multi_sensor_corroborated_location() -> None:
    matches = [
        {
            "speed_kmh": 92.0,
            "amp": 0.120,
            "location": "Front Right",
            "matched_hz": 33.0,
            "rel_error": 0.40,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.055,
            "location": "Front Left",
            "matched_hz": 40.0,
            "rel_error": 0.01,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.048,
            "location": "Rear Left",
            "matched_hz": 40.1,
            "rel_error": 0.01,
        },
        {
            "speed_kmh": 92.0,
            "amp": 0.047,
            "location": "Rear Right",
            "matched_hz": 39.9,
            "rel_error": 0.01,
        },
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en")
    assert hotspot is not None
    assert hotspot.get("top_location") == "Front Left"
    assert int(hotspot.get("corroborated_by_n_sensors") or 0) >= 3


def test_location_speedbin_summary_prefers_connected_throughout_locations() -> None:
    matches = [
        {"speed_kmh": 85.0, "amp": 0.022, "location": "Front Left"},
        {"speed_kmh": 86.0, "amp": 0.023, "location": "Front Left"},
        {"speed_kmh": 85.0, "amp": 0.050, "location": "Rear Right"},
        {"speed_kmh": 86.0, "amp": 0.048, "location": "Rear Right"},
    ]

    _, hotspot = _location_speedbin_summary(matches, lang="en", connected_locations={"Front Left"})
    assert hotspot is not None
    assert hotspot.get("top_location") == "Front Left"
    assert bool(hotspot.get("partial_coverage")) is False


def test_build_findings_penalizes_low_localization_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = []
    for idx in range(24):
        speed = 70.0 + idx
        wh = wheel_hz_from_speed_kmh(speed, 2.036) or 10.0
        samples.append(
            {**_make_sample(float(idx), speed, 0.03), "top_peaks": [{"hz": wh, "amp": 0.03}]},
        )

    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "strong location",
            {
                "location": "Front Left",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 2.0,
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
            },
        ),
    )
    high_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "ambiguous location",
            {
                "location": "ambiguous location: Front Left / Front Right",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.05,
                "weak_spatial_separation": False,
                "localization_confidence": 0.1,
            },
        ),
    )
    low_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    assert low_conf < high_conf


def test_build_findings_penalizes_weak_spatial_separation_by_dominance_ratio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = []
    for idx in range(24):
        speed = 65.0 + idx
        wh = wheel_hz_from_speed_kmh(speed, 2.036) or 10.0
        samples.append(
            {**_make_sample(float(idx), speed, 0.03), "top_peaks": [{"hz": wh, "amp": 0.03}]},
        )

    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "strong location",
            {
                "location": "Front Left",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 2.0,
                "weak_spatial_separation": False,
                "localization_confidence": 1.0,
            },
        ),
    )
    baseline_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "weak location",
            {
                "location": "Front Left",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.15,
                "weak_spatial_separation": True,
                "localization_confidence": 1.0,
            },
        ),
    )
    weak_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        order_findings_module,
        "_location_speedbin_summary",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "near tie location",
            {
                "location": "ambiguous location: Front Left / Front Right",
                "speed_range": "70-80 km/h",
                "dominance_ratio": 1.04,
                "weak_spatial_separation": True,
                "localization_confidence": 1.0,
            },
        ),
    )
    near_tie_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    assert weak_conf <= (baseline_conf * 0.80) + 1e-9
    assert near_tie_conf <= (baseline_conf * 0.70) + 1e-9
    assert near_tie_conf < weak_conf


def test_build_findings_excludes_partial_coverage_sensor_from_strongest_location() -> None:
    samples: list[dict[str, object]] = []
    for idx in range(20):
        speed_kmh = 70.0 + idx
        wh = wheel_hz_from_speed_kmh(speed_kmh, 2.036) or 10.0
        samples.append(
            {
                **_make_sample(float(idx), speed_kmh, 0.02),
                "client_name": "Front Left",
                "strength_floor_amp_g": 0.002,
                "top_peaks": [{"hz": wh, "amp": 0.02}],
            },
        )
        if idx < 6:
            samples.append(
                {
                    **_make_sample(float(idx), speed_kmh, 0.05),
                    "client_name": "Rear Right",
                    "strength_floor_amp_g": 0.002,
                    "top_peaks": [{"hz": wh, "amp": 0.05}],
                },
            )

    findings = build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en")
    wheel_finding = next(
        (finding for finding in findings if str(finding.get("finding_key") or "") == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    assert wheel_finding.get("strongest_location") == "Front Left"
    hotspot = wheel_finding.get("location_hotspot")
    assert isinstance(hotspot, dict)
    assert bool(hotspot.get("partial_coverage")) is False
