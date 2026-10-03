"""OrderMatchObservation match semantics, invariants and boundary codec."""

from __future__ import annotations

import pytest

from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.summary.finding_fields import order_match_observation_from_mapping


class TestOrderMatchObservation:
    @pytest.mark.parametrize(
        ("rel_error", "expected"),
        [
            pytest.param(0.0, True, id="exact"),
            pytest.param(0.05, True, id="threshold-inclusive"),
            pytest.param(0.0501, False, id="above-threshold"),
        ],
    )
    def test_is_close_match_uses_inclusive_five_percent_threshold(
        self,
        rel_error: float,
        expected: bool,
    ) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=100.0 * (1.0 + rel_error),
            rel_error=rel_error,
            amp=1.0,
            location="front_left",
        )

        assert obs.is_close_match is expected

    @pytest.mark.parametrize(
        ("matched_hz", "expected_error"),
        [
            pytest.param(105.0, 5.0, id="above-predicted"),
            pytest.param(95.0, 5.0, id="below-predicted"),
        ],
    )
    def test_frequency_error_hz_is_absolute(
        self,
        matched_hz: float,
        expected_error: float,
    ) -> None:
        obs = OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=matched_hz,
            rel_error=0.05,
            amp=1.0,
            location="front_left",
        )
        assert obs.frequency_error_hz == expected_error

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            pytest.param({"predicted_hz": 0.0}, "predicted_hz", id="zero-predicted"),
            pytest.param({"rel_error": -0.1}, "rel_error", id="negative-rel-error"),
        ],
    )
    def test_invalid_frequency_contract_rejected(
        self,
        overrides: dict[str, float],
        message: str,
    ) -> None:
        payload = {
            "predicted_hz": 100.0,
            "matched_hz": 100.0,
            "rel_error": 0.0,
            "amp": 1.0,
        }
        payload.update(overrides)
        with pytest.raises(ValueError, match=message):
            OrderMatchObservation(
                predicted_hz=payload["predicted_hz"],
                matched_hz=payload["matched_hz"],
                rel_error=payload["rel_error"],
                amp=payload["amp"],
                location="front_left",
            )

    def test_boundary_codec_from_mapping(self) -> None:
        raw = {
            "predicted_hz": 100.0,
            "matched_hz": 102.0,
            "rel_error": 0.02,
            "amp": 0.5,
            "location": "front_left",
            "t_s": 1.5,
            "speed_kmh": 60.0,
            "phase": "cruise",
        }
        obs = order_match_observation_from_mapping(raw)
        assert obs == OrderMatchObservation(
            predicted_hz=100.0,
            matched_hz=102.0,
            rel_error=0.02,
            amp=0.5,
            location="front_left",
            t_s=1.5,
            speed_kmh=60.0,
            phase="cruise",
        )

    def test_boundary_codec_missing_optional_keys(self) -> None:
        raw = {
            "predicted_hz": 100.0,
            "matched_hz": 100.0,
            "rel_error": 0.0,
            "amp": 1.0,
            "location": "x",
        }
        obs = order_match_observation_from_mapping(raw)
        assert obs.t_s is None
        assert obs.speed_kmh is None
        assert obs.phase is None
