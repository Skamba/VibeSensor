"""Tests for domain strength measurement value objects."""

from __future__ import annotations

import pytest

from vibesensor.shared.boundaries.codecs import (
    strength_metrics_from_mapping,
    strength_peak_from_mapping,
    strength_peak_payloads,
    strength_peak_to_payload,
)


@pytest.mark.parametrize(
    ("decoder", "payload", "extract", "expected"),
    [
        pytest.param(
            strength_peak_from_mapping,
            {},
            lambda peak: {
                "hz": peak.hz,
                "amp": peak.amp,
                "vibration_strength_db": peak.vibration_strength_db,
                "strength_bucket": peak.strength_bucket,
            },
            {
                "hz": 0.0,
                "amp": 0.0,
                "vibration_strength_db": None,
                "strength_bucket": None,
            },
            id="strength-peak-empty",
        ),
        pytest.param(
            strength_peak_from_mapping,
            {
                "hz": 42.5,
                "amp": 0.03,
                "vibration_strength_db": 12.3,
                "strength_bucket": "moderate",
            },
            lambda peak: {
                "hz": peak.hz,
                "amp": peak.amp,
                "vibration_strength_db": peak.vibration_strength_db,
                "strength_bucket": peak.strength_bucket,
            },
            {
                "hz": 42.5,
                "amp": 0.03,
                "vibration_strength_db": 12.3,
                "strength_bucket": "moderate",
            },
            id="strength-peak-round-trip",
        ),
        pytest.param(
            strength_metrics_from_mapping,
            {},
            lambda metrics: {
                "vibration_strength_db": metrics.vibration_strength_db,
                "peak_amp_g": metrics.peak_amp_g,
                "noise_floor_amp_g": metrics.noise_floor_amp_g,
                "strength_bucket": metrics.strength_bucket,
                "top_peaks": metrics.top_peaks,
            },
            {
                "vibration_strength_db": None,
                "peak_amp_g": None,
                "noise_floor_amp_g": None,
                "strength_bucket": None,
                "top_peaks": (),
            },
            id="strength-metrics-empty",
        ),
        pytest.param(
            strength_metrics_from_mapping,
            {
                "vibration_strength_db": 18.5,
                "peak_amp_g": 0.05,
                "noise_floor_amp_g": 0.002,
                "strength_bucket": "strong",
                "top_peaks": [
                    {
                        "hz": 42.0,
                        "amp": 0.05,
                        "vibration_strength_db": 18.5,
                        "strength_bucket": "strong",
                    },
                    {
                        "hz": 84.0,
                        "amp": 0.02,
                        "vibration_strength_db": 10.0,
                        "strength_bucket": "moderate",
                    },
                ],
            },
            lambda metrics: {
                "vibration_strength_db": metrics.vibration_strength_db,
                "peak_amp_g": metrics.peak_amp_g,
                "noise_floor_amp_g": metrics.noise_floor_amp_g,
                "strength_bucket": metrics.strength_bucket,
                "top_peaks": tuple(
                    (peak.hz, peak.amp, peak.vibration_strength_db, peak.strength_bucket)
                    for peak in metrics.top_peaks
                ),
            },
            {
                "vibration_strength_db": 18.5,
                "peak_amp_g": 0.05,
                "noise_floor_amp_g": 0.002,
                "strength_bucket": "strong",
                "top_peaks": (
                    (42.0, 0.05, 18.5, "strong"),
                    (84.0, 0.02, 10.0, "moderate"),
                ),
            },
            id="strength-metrics-round-trip",
        ),
    ],
)
def test_strength_codecs_decode_expected_fields(decoder, payload, extract, expected) -> None:
    assert extract(decoder(payload)) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param({"hz": "bad"}, {"hz": 0.0, "amp": 0.0}, id="invalid-hz"),
        pytest.param({"amp": float("inf")}, {"hz": 0.0, "amp": 0.0}, id="infinite-amp"),
        pytest.param({"strength_bucket": ""}, {"strength_bucket": None}, id="empty-bucket"),
    ],
)
def test_strength_peak_from_mapping_sanitizes_invalid_inputs(
    payload: dict[str, object],
    expected: dict[str, object],
) -> None:
    peak = strength_peak_from_mapping(payload)
    for field, expected_value in expected.items():
        assert getattr(peak, field) == expected_value


def test_strength_peak_to_payload_omits_missing_optional_fields() -> None:
    peak = strength_peak_from_mapping({"hz": 42.0, "amp": 0.3})
    assert strength_peak_to_payload(peak) == {"hz": 42.0, "amp": 0.3}


def test_strength_peak_is_valid_requires_positive_hz_and_amp() -> None:
    assert strength_peak_from_mapping({"hz": 42.0, "amp": 0.3}).is_valid is True
    assert strength_peak_from_mapping({"hz": 0.0, "amp": 0.3}).is_valid is False
    assert strength_peak_from_mapping({"hz": 42.0, "amp": 0.0}).is_valid is False


@pytest.mark.parametrize(
    ("payload", "expected_hz_values", "expected_dominant_hz"),
    [
        pytest.param({}, (), None, id="empty-defaults"),
        pytest.param({"vibration_strength_db": 5.0}, (), None, id="missing-top-peaks"),
        pytest.param(
            {"top_peaks": [42, "bad", {"hz": 10.0}]},
            (10.0,),
            10.0,
            id="skip-non-mapping-items",
        ),
        pytest.param(
            {"top_peaks": [{"hz": "bad", "amp": 0.05}]},
            (0.0,),
            None,
            id="invalid-first-peak-drops-dominant-hz",
        ),
    ],
)
def test_strength_metrics_from_mapping_handles_missing_and_invalid_peak_inputs(
    payload: dict[str, object],
    expected_hz_values: tuple[float, ...],
    expected_dominant_hz: float | None,
) -> None:
    metrics = strength_metrics_from_mapping(payload)

    assert isinstance(metrics.top_peaks, tuple)
    assert tuple(peak.hz for peak in metrics.top_peaks) == expected_hz_values
    assert metrics.dominant_hz == expected_dominant_hz


def test_strength_metrics_dominant_peak_and_hz_follow_first_typed_peak() -> None:
    metrics = strength_metrics_from_mapping(
        {
            "top_peaks": [
                {"hz": 42.0, "amp": 0.05},
                {"hz": 84.0, "amp": 0.04},
            ],
        },
    )
    assert metrics.dominant_peak is not None
    assert metrics.dominant_peak.hz == 42.0
    assert metrics.dominant_hz == 42.0


def test_strength_metrics_to_peak_payloads_filters_invalid_peaks_and_truncates() -> None:
    metrics = strength_metrics_from_mapping(
        {
            "top_peaks": [
                {"hz": float(i), "amp": 0.1, "vibration_strength_db": float(i)}
                for i in range(1, 11)
            ]
            + [
                {"hz": 100.0, "amp": 0.0},
                {"hz": 0.0, "amp": 0.3},
            ],
        },
    )

    payloads = strength_peak_payloads(metrics.top_peaks, max_items=8)

    assert len(payloads) == 8
    assert payloads[0] == {"hz": 1.0, "amp": 0.1, "vibration_strength_db": 1.0}
    assert payloads[-1] == {"hz": 8.0, "amp": 0.1, "vibration_strength_db": 8.0}
