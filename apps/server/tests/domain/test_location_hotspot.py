"""Tests for LocationHotspot.compute_confidence()."""

from __future__ import annotations

import pytest

from vibesensor.domain.location_hotspot import LocationHotspot


class TestComputeConfidence:
    """LocationHotspot.compute_confidence staticmethod."""

    def test_high_dominance_few_locations(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.6,
            location_count=1,
            total_samples=20,
        )
        assert result > 0.9

    def test_low_dominance_many_locations(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.05,
            location_count=6,
            total_samples=20,
        )
        assert result < 0.2

    def test_zero_samples_gives_minimum(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.5,
            location_count=1,
            total_samples=0,
        )
        assert result == pytest.approx(0.6 * 1.0 * 1.0, abs=0.01)
        # dominance_component=1.0, location_component=1.0, sample_component=0.0
        # confidence = 1.0 * 1.0 * (0.6 + 0.4*0.0) = 0.6

    def test_minimum_floor(self) -> None:
        # dominance_ratio <= 1.0 → dominance_component = 0 → confidence → 0
        # but floor is 0.05
        result = LocationHotspot.compute_confidence(
            dominance_ratio=0.5,
            location_count=1,
            total_samples=100,
        )
        assert result == pytest.approx(0.05)

    def test_maximum_cap(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=10.0,
            location_count=1,
            total_samples=1000,
        )
        assert result == pytest.approx(1.0)

    def test_dominance_exactly_one(self) -> None:
        # (1.0 - 1.0) / 0.5 = 0.0 → dominance_component = 0
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.0,
            location_count=1,
            total_samples=50,
        )
        assert result == pytest.approx(0.05)

    def test_partial_dominance(self) -> None:
        # dominance_ratio=1.25 → (0.25/0.5)=0.5
        # location_count=2 → 1/(1+0.15)=0.8696
        # total_samples=10 → sample_component=1.0
        # confidence = 0.5 * 0.8696 * 1.0 ≈ 0.4348
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.25,
            location_count=2,
            total_samples=10,
        )
        expected = 0.5 * (1.0 / 1.15) * (0.6 + 0.4 * 1.0)
        assert result == pytest.approx(expected, abs=0.001)

    def test_low_sample_count_reduces_confidence(self) -> None:
        high_samples = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=50,
        )
        low_samples = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=3,
        )
        assert high_samples > low_samples

    def test_more_locations_reduces_confidence(self) -> None:
        few = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=20,
        )
        many = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=5,
            total_samples=20,
        )
        assert few > many
