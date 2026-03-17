"""Tests for domain strength measurement value objects."""

from __future__ import annotations

import pytest

from vibesensor.domain import StrengthMetrics, StrengthPeak

# ── StrengthPeak ────────────────────────────────────────────────────


class TestStrengthPeakFromDict:
    def test_empty_dict_never_raises(self) -> None:
        p = StrengthPeak.from_dict({})
        assert p.hz == 0.0
        assert p.amp == 0.0
        assert p.vibration_strength_db is None
        assert p.strength_bucket is None

    def test_round_trip(self) -> None:
        data = {
            "hz": 42.5,
            "amp": 0.03,
            "vibration_strength_db": 12.3,
            "strength_bucket": "moderate",
        }
        p = StrengthPeak.from_dict(data)
        assert p.hz == 42.5
        assert p.amp == 0.03
        assert p.vibration_strength_db == pytest.approx(12.3)
        assert p.strength_bucket == "moderate"

    def test_invalid_hz_defaults(self) -> None:
        p = StrengthPeak.from_dict({"hz": "bad"})
        assert p.hz == 0.0

    def test_infinity_defaults(self) -> None:
        p = StrengthPeak.from_dict({"amp": float("inf")})
        assert p.amp == 0.0

    def test_to_dict_omits_missing_optional_fields(self) -> None:
        p = StrengthPeak.from_dict({"hz": 42.0, "amp": 0.3})
        assert p.to_dict() == {"hz": 42.0, "amp": 0.3}

    def test_empty_bucket_becomes_none(self) -> None:
        p = StrengthPeak.from_dict({"strength_bucket": ""})
        assert p.strength_bucket is None

    def test_is_valid_requires_positive_hz_and_amp(self) -> None:
        assert StrengthPeak.from_dict({"hz": 42.0, "amp": 0.3}).is_valid is True
        assert StrengthPeak.from_dict({"hz": 0.0, "amp": 0.3}).is_valid is False
        assert StrengthPeak.from_dict({"hz": 42.0, "amp": 0.0}).is_valid is False


# ── StrengthMetrics ─────────────────────────────────────────────────


class TestStrengthMetricsFromDict:
    def test_empty_dict_never_raises(self) -> None:
        m = StrengthMetrics.from_dict({})
        assert m.vibration_strength_db is None
        assert m.peak_amp_g is None
        assert m.noise_floor_amp_g is None
        assert m.strength_bucket is None
        assert m.top_peaks == ()

    def test_round_trip(self) -> None:
        data = {
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
        }
        m = StrengthMetrics.from_dict(data)
        assert m.vibration_strength_db == pytest.approx(18.5)
        assert len(m.top_peaks) == 2
        assert m.top_peaks[0].hz == 42.0
        assert m.top_peaks[1].strength_bucket == "moderate"

    def test_non_mapping_peaks_skipped(self) -> None:
        m = StrengthMetrics.from_dict({"top_peaks": [42, "bad", {"hz": 10.0}]})
        assert len(m.top_peaks) == 1
        assert m.top_peaks[0].hz == 10.0

    def test_no_top_peaks_key(self) -> None:
        m = StrengthMetrics.from_dict({"vibration_strength_db": 5.0})
        assert m.top_peaks == ()

    def test_from_typed_dict_alias(self) -> None:
        data = {
            "vibration_strength_db": 7.0,
            "peak_amp_g": 0.01,
            "noise_floor_amp_g": 0.001,
            "strength_bucket": None,
            "top_peaks": [],
        }
        m = StrengthMetrics.from_typed_dict(data)
        assert m.vibration_strength_db == 7.0
        assert m.top_peaks == ()

    def test_top_peaks_immutable(self) -> None:
        m = StrengthMetrics.from_dict({"top_peaks": [{"hz": 1.0}]})
        assert isinstance(m.top_peaks, tuple)

    def test_dominant_peak_and_hz_follow_first_typed_peak(self) -> None:
        m = StrengthMetrics.from_dict(
            {
                "top_peaks": [
                    {"hz": 42.0, "amp": 0.05},
                    {"hz": 84.0, "amp": 0.04},
                ],
            },
        )
        assert m.dominant_peak is not None
        assert m.dominant_peak.hz == 42.0
        assert m.dominant_hz == 42.0

    def test_dominant_hz_degrades_gracefully_for_invalid_first_peak(self) -> None:
        m = StrengthMetrics.from_dict({"top_peaks": [{"hz": "bad", "amp": 0.05}]})
        assert m.dominant_hz is None

    def test_to_peak_payloads_filters_invalid_peaks_and_truncates(self) -> None:
        m = StrengthMetrics.from_dict(
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

        payloads = m.to_peak_payloads(max_items=8)

        assert len(payloads) == 8
        assert payloads[0] == {"hz": 1.0, "amp": 0.1, "vibration_strength_db": 1.0}
        assert payloads[-1] == {"hz": 8.0, "amp": 0.1, "vibration_strength_db": 8.0}
