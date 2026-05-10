from __future__ import annotations

import numpy as np

from vibesensor.shared._window_quality_metrics import (
    analyze_mounting_artifact,
    analyze_window_clipping,
    analyze_window_transient,
)
from vibesensor.shared._window_quality_scoring import _quality_from_component_scores
from vibesensor.shared._window_quality_types import WindowQuality


def test_window_quality_metric_layer_normalizes_axis_orientation_for_clipping() -> None:
    samples_i16 = np.zeros((3, 64), dtype=np.int16)
    samples_i16[1, 10:14] = 32767

    analysis = analyze_window_clipping(samples_i16=samples_i16)

    assert analysis.score == 0.0
    assert analysis.sample_count == 4
    assert analysis.axis_counts == (0, 4, 0)
    assert analysis.axis_counts_payload() == {"x": 0, "y": 4, "z": 0}


def test_window_quality_metric_layer_reports_transient_and_mounting_facts() -> None:
    impulse = np.zeros((256, 3), dtype=np.float32)
    impulse[128, 0] = 16.0
    high_frequency = np.sin(np.arange(256, dtype=np.float32) * np.float32(2.2)).reshape(-1, 1)
    high_frequency = np.column_stack(
        [high_frequency[:, 0], np.zeros(256, dtype=np.float32), np.zeros(256, dtype=np.float32)]
    )

    transient = analyze_window_transient(impulse)
    mounting = analyze_mounting_artifact(high_frequency, sample_rate_hz=256)

    assert transient.score < 0.25
    assert transient.crest_factor is not None
    assert transient.broadband_ratio is not None
    assert mounting.score < 0.50
    assert mounting.high_frequency_ratio is not None


def test_window_quality_scoring_layer_assembles_reasons_and_state_once() -> None:
    quality = _quality_from_component_scores(
        sample_completeness_score=0.50,
        packet_integrity_score=0.45,
        timing_integrity_score=0.35,
        timing_reasons=("timing_gap", "timing_gap", "server_queue_drop"),
        clipping_score=1.0,
        transient_score=1.0,
        mounting_score=1.0,
        context_score=0.65,
        context_reasons=("speed_stale",),
        frequency_stability_score=0.60,
    )

    assert quality.state == "excluded"
    assert quality.reasons == (
        "sample_incomplete",
        "packet_integrity_gap",
        "timing_gap",
        "server_queue_drop",
        "speed_stale",
        "context_unavailable",
        "frequency_unstable",
    )


def test_window_quality_type_layer_filters_unknown_reasons_and_payload_keys() -> None:
    quality = WindowQuality.from_mapping(
        {
            "score": 1.2,
            "state": "unexpected",
            "clipping_axis_counts": {"x": 2, "y": -4, "z": 5},
            "reasons": ["timing_gap", "unknown_reason", "speed_stale"],
        }
    )

    assert quality.score == 1.0
    assert quality.state == "usable"
    assert quality.clipping_axis_counts == (2, 0, 5)
    assert quality.reasons == ("timing_gap", "speed_stale")
    assert set(quality.to_payload()) == {
        "score",
        "state",
        "sample_completeness_score",
        "packet_integrity_score",
        "timing_integrity_score",
        "clipping_score",
        "clipping_sample_count",
        "clipping_sample_ratio",
        "clipping_axis_counts",
        "transient_score",
        "shock_crest_factor",
        "shock_broadband_ratio",
        "mounting_score",
        "mounting_high_frequency_ratio",
        "context_score",
        "frequency_stability_score",
        "reasons",
    }
