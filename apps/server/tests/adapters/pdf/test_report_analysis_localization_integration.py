from __future__ import annotations

import pytest
from test_support.report_helpers import analysis_sample as _make_sample
from test_support.report_helpers import max_non_ref_confidence, wheel_metadata

from vibesensor.domain import LocationHotspot, OrderMatchObservation
from vibesensor.shared.boundaries.finding import finding_from_payload
from vibesensor.shared.constants import KMH_TO_MPS
from vibesensor.use_cases.diagnostics import build_findings_for_samples
from vibesensor.use_cases.diagnostics import order_scoring as _order_scoring_module
from vibesensor.use_cases.diagnostics.location_analysis import (
    LocationAnalysisResult,
    summarize_order_match_locations,
)
from vibesensor.use_cases.diagnostics.summary_builder import summarize_origin


def _obs(
    speed_kmh: float,
    amp: float,
    location: str,
    matched_hz: float = 1.0,
    rel_error: float = 0.0,
) -> OrderMatchObservation:
    return OrderMatchObservation(
        predicted_hz=1.0,
        matched_hz=matched_hz or 1.0,
        rel_error=rel_error,
        amp=amp,
        location=location,
        speed_kmh=speed_kmh,
    )


def _make_loc_result(
    *,
    location: str = "Front Left",
    speed_range: str = "70-80 km/h",
    dominance_ratio: float = 2.0,
    weak_spatial_separation: bool = False,
    localization_confidence: float = 1.0,
    no_wheel_sensors: bool = False,
    ambiguous_location: bool = False,
    mean_amp: float = 0.03,
    total_samples: int = 10,
) -> LocationAnalysisResult:
    """Build a LocationAnalysisResult for monkeypatch stubs."""
    top_loc = location
    second_loc: str | None = None
    ambiguous_locs: list[str] = []
    if "ambiguous" in location.lower() and "/" in location:
        parts = location.split("/")
        top_loc = parts[0].replace("ambiguous location:", "").strip()
        second_loc = parts[1].strip() if len(parts) > 1 else None
        ambiguous_locs = [top_loc]
        if second_loc:
            ambiguous_locs.append(second_loc)
        ambiguous_location = True
    return LocationAnalysisResult(
        hotspot=LocationHotspot.from_analysis_inputs(
            strongest_location=top_loc,
            dominance_ratio=dominance_ratio,
            localization_confidence=localization_confidence,
            weak_spatial_separation=weak_spatial_separation,
            ambiguous=ambiguous_location,
            alternative_locations=ambiguous_locs,
        ),
        mean_amp=mean_amp,
        total_samples=total_samples,
        ambiguous_location=ambiguous_location,
        no_wheel_sensors=no_wheel_sensors,
        speed_range=speed_range,
        dominance_ratio=dominance_ratio,
        localization_confidence=localization_confidence,
        weak_spatial_separation=weak_spatial_separation,
        top_location=top_loc,
        second_location=second_loc,
        partial_coverage=False,
        corroborated_by_n_sensors=1,
    )


def test_summarize_order_match_locations_reports_ambiguous_location_for_near_tie() -> None:
    matches = [
        _obs(85.0, 0.0110, "Rear Right"),
        _obs(85.0, 0.0102, "Rear Left"),
        _obs(86.0, 0.0112, "Rear Right"),
        _obs(86.0, 0.0103, "Rear Left"),
    ]

    sentence, hotspot = summarize_order_match_locations(matches, lang="en")

    assert hotspot is not None
    assert hotspot.ambiguous_location
    assert hotspot.display_location == "ambiguous location: Rear Right / Rear Left"
    assert list(hotspot.hotspot.alternative_locations) == ["Rear Right", "Rear Left"]
    assert hotspot.localization_confidence < 0.4
    assert isinstance(sentence, dict)
    assert sentence.get("_i18n_key") == "STRONGEST_AT_LOCATION_IN_SPEED_RANGE"
    assert "ambiguous location" in str(sentence.get("location", ""))


def test_summarize_order_match_locations_weak_spatial_threshold_adapts_to_location_count() -> None:
    base_matches = [
        _obs(85.0, 1.30, "Front Left"),
        _obs(85.0, 1.00, "Front Right"),
    ]

    _, hotspot_2 = summarize_order_match_locations(base_matches, lang="en")
    assert hotspot_2 is not None
    assert hotspot_2.weak_spatial_separation is False

    _, hotspot_3 = summarize_order_match_locations(
        base_matches + [_obs(85.0, 0.40, "Rear Left")],
        lang="en",
    )
    assert hotspot_3 is not None
    assert hotspot_3.weak_spatial_separation is True

    _, hotspot_4 = summarize_order_match_locations(
        base_matches
        + [
            _obs(85.0, 0.40, "Rear Left"),
            _obs(85.0, 0.35, "Rear Right"),
        ],
        lang="en",
    )
    assert hotspot_4 is not None
    assert hotspot_4.weak_spatial_separation is True


def test_most_likely_origin_summary_uses_adaptive_weak_spatial_fallback() -> None:
    f = finding_from_payload(
        {
            "suspected_source": "wheel/tire",
            "strongest_location": "Front Left",
            "strongest_speed_band": "80-90 km/h",
            "dominance_ratio": 1.30,
            "weak_spatial_separation": False,
            "location_hotspot": {"location_count": 3},
            "confidence": 0.8,
        },
    )
    origin = summarize_origin((f,))
    assert origin is not None
    assert origin.weak_spatial_separation is True


def test_summarize_order_match_locations_can_restrict_to_relevant_speed_bins() -> None:
    matches = [
        _obs(65.0, 0.030, "Rear Left"),
        _obs(66.0, 0.028, "Rear Left"),
        _obs(105.0, 0.019, "Front Right"),
        _obs(106.0, 0.020, "Front Right"),
    ]

    _, unconstrained = summarize_order_match_locations(matches, lang="en")
    _, focused = summarize_order_match_locations(
        matches,
        lang="en",
        relevant_speed_bins=["100-110 km/h"],
    )

    assert unconstrained is not None
    assert focused is not None
    assert unconstrained.display_location == "Rear Left"
    assert focused.display_location == "Front Right"
    focused_range = focused.speed_range
    low_text, high_text = focused_range.replace(" km/h", "").split("-", maxsplit=1)
    assert float(low_text) >= 100.0
    assert float(high_text) <= 110.0


def test_summarize_order_match_locations_reports_weighted_boundary_straddling_window() -> None:
    matches = [
        _obs(74.0, 0.005, "Front Left"),
        _obs(75.0, 0.005, "Front Left"),
        _obs(76.0, 0.030, "Front Left"),
        _obs(77.0, 0.030, "Front Left"),
        _obs(78.0, 0.030, "Front Left"),
        _obs(79.0, 0.030, "Front Left"),
        _obs(80.0, 0.030, "Front Left"),
        _obs(81.0, 0.030, "Front Left"),
        _obs(82.0, 0.030, "Front Left"),
        _obs(83.0, 0.030, "Front Left"),
        _obs(84.0, 0.005, "Front Left"),
    ]

    _, hotspot = summarize_order_match_locations(matches, lang="en")
    assert hotspot is not None
    speed_range = hotspot.speed_range
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 75.0 <= low <= 77.0
    assert 83.0 <= high <= 85.0
    assert speed_range not in {"70-80 km/h", "80-90 km/h"}


def test_summarize_order_match_locations_prefers_better_sample_coverage_over_tiny_outlier_bin() -> (
    None
):
    sparse_loud_bin = [
        _obs(85.0, 0.120, "Rear Left"),
        _obs(86.0, 0.120, "Rear Left"),
    ]
    dense_moderate_bin = [_obs(95.0 + (0.1 * idx), 0.090, "Front Left") for idx in range(20)]

    _, hotspot = summarize_order_match_locations(
        sparse_loud_bin + dense_moderate_bin,
        lang="en",
    )
    assert hotspot is not None
    assert hotspot.display_location == "Front Left"
    speed_range = hotspot.speed_range
    low_text, high_text = speed_range.replace(" km/h", "").split("-", maxsplit=1)
    low, high = float(low_text), float(high_text)
    assert 95.0 <= low <= high <= 97.0


def test_summarize_order_match_locations_prefers_multi_sensor_corroborated_location() -> None:
    matches = [
        _obs(92.0, 0.120, "Front Right", matched_hz=33.0, rel_error=0.40),
        _obs(92.0, 0.055, "Front Left", matched_hz=40.0, rel_error=0.01),
        _obs(92.0, 0.048, "Rear Left", matched_hz=40.1, rel_error=0.01),
        _obs(92.0, 0.047, "Rear Right", matched_hz=39.9, rel_error=0.01),
    ]

    _, hotspot = summarize_order_match_locations(matches, lang="en")
    assert hotspot is not None
    assert hotspot.top_location == "Front Left"
    assert hotspot.corroborated_by_n_sensors >= 3


def test_summarize_order_match_locations_prefers_connected_throughout_locations() -> None:
    matches = [
        _obs(85.0, 0.022, "Front Left"),
        _obs(86.0, 0.023, "Front Left"),
        _obs(85.0, 0.050, "Rear Right"),
        _obs(86.0, 0.048, "Rear Right"),
    ]

    _, hotspot = summarize_order_match_locations(
        matches,
        lang="en",
        connected_locations={"Front Left"},
    )
    assert hotspot is not None
    assert hotspot.top_location == "Front Left"
    assert hotspot.partial_coverage is False


def test_build_findings_penalizes_low_localization_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    samples = []
    for idx in range(24):
        speed = 70.0 + idx
        wh = speed * KMH_TO_MPS / 2.036
        samples.append(
            {**_make_sample(float(idx), speed, 0.03), "top_peaks": [{"hz": wh, "amp": 0.03}]},
        )

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "strong location",
            _make_loc_result(
                location="Front Left",
                speed_range="70-80 km/h",
                dominance_ratio=2.0,
                weak_spatial_separation=False,
                localization_confidence=1.0,
            ),
        ),
    )
    high_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "ambiguous location",
            _make_loc_result(
                location="ambiguous location: Front Left / Front Right",
                speed_range="70-80 km/h",
                dominance_ratio=1.05,
                weak_spatial_separation=False,
                localization_confidence=0.1,
            ),
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
        wh = speed * KMH_TO_MPS / 2.036
        samples.append(
            {**_make_sample(float(idx), speed, 0.03), "top_peaks": [{"hz": wh, "amp": 0.03}]},
        )

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "strong location",
            _make_loc_result(
                location="Front Left",
                speed_range="70-80 km/h",
                dominance_ratio=2.0,
                weak_spatial_separation=False,
                localization_confidence=1.0,
            ),
        ),
    )
    baseline_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "weak location",
            _make_loc_result(
                location="Front Left",
                speed_range="70-80 km/h",
                dominance_ratio=1.15,
                weak_spatial_separation=True,
                localization_confidence=1.0,
            ),
        ),
    )
    weak_conf = max_non_ref_confidence(
        build_findings_for_samples(metadata=wheel_metadata(), samples=samples, lang="en"),
    )

    monkeypatch.setattr(
        _order_scoring_module,
        "summarize_order_match_locations",
        lambda matched_points, lang, relevant_speed_bins=None, connected_locations=None, **_kw: (
            "near tie location",
            _make_loc_result(
                location="ambiguous location: Front Left / Front Right",
                speed_range="70-80 km/h",
                dominance_ratio=1.04,
                weak_spatial_separation=True,
                localization_confidence=1.0,
            ),
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
        wh = speed_kmh * KMH_TO_MPS / 2.036
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
        (finding for finding in findings if finding.finding_key == "wheel_1x"),
        None,
    )

    assert wheel_finding is not None
    assert wheel_finding.strongest_location == "Front Left"
