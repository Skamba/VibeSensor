"""OrderMatchObservation match semantics, invariants and boundary codec."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.summary.finding_fields import order_match_observation_from_mapping


class TestOrderMatchObservation:
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

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(
                {
                    "predicted_hz": 100.0,
                    "matched_hz": 101.5,
                    "rel_error": 0.015,
                    "amp": 0.25,
                    "location": "rear_axle",
                    "t_s": 3.0,
                    "speed_kmh": 80.0,
                    "phase": "cruise",
                    "heard": True,
                },
                id="stored-point",
            ),
            pytest.param(
                {
                    "predicted_hz": 100,
                    "matched_hz": 99,
                    "rel_error": 0.01,
                    "amp": 1,
                    "location": "x",
                },
                id="integers",
            ),
            pytest.param(
                {"predicted_hz": "100.0", "matched_hz": 100.0, "rel_error": 0.0, "amp": "bad"},
                id="strings-and-no-location",
            ),
            pytest.param(
                {
                    "predicted_hz": 100.0,
                    "matched_hz": 100.0,
                    "rel_error": 0.0,
                    "amp": 1.0,
                    "location": 7,
                    "t_s": "2.5",
                    "phase": 3,
                    "heard": 1,
                },
                id="odd-types",
            ),
        ],
    )
    def test_plain_dict_decodes_like_any_mapping(self, raw: dict[str, object]) -> None:
        assert order_match_observation_from_mapping(raw) == order_match_observation_from_mapping(
            MappingProxyType(raw)
        )
