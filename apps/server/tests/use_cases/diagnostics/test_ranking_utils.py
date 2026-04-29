"""Focused regressions for shared diagnostics ranking helpers."""

from __future__ import annotations

from vibesensor.use_cases.diagnostics._ranking_utils import (
    dominant_weighted_value,
    sortable_optional_metric,
)


def test_dominant_weighted_value_keeps_count_weight_and_value_tiebreaks() -> None:
    assert (
        dominant_weighted_value(
            values=(
                ("front-left", 1.0),
                ("rear-right", 5.0),
                ("front-left", 0.5),
            )
        )
        == "front-left"
    )
    assert (
        dominant_weighted_value(
            values=(
                ("alpha", 1.0),
                ("bravo", 1.0),
            )
        )
        == "bravo"
    )


def test_sortable_optional_metric_sends_missing_values_last() -> None:
    assert sortable_optional_metric(4.5) == 4.5
    assert sortable_optional_metric(None) == float("-inf")
