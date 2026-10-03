from __future__ import annotations

import numpy as np

from vibesensor.dsp.window_quality_metrics import (
    analyze_mounting_artifact,
    analyze_window_clipping,
    analyze_window_transient,
)
from vibesensor.dsp.window_quality_scoring import _quality_from_component_scores


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
