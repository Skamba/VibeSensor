from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter

from vibesensor.shared.types.analysis_views import (
    FindingEvidenceMetrics,
    LocationHotspotPayload,
    MatchedPoint,
    PeakTableRow,
    PhaseEvidence,
    PlotDataResult,
    SpectrogramResult,
)

_SPECTROGRAM: SpectrogramResult = {
    "x_axis": "speed_kmh",
    "x_label_key": "speed",
    "x_bins": [10.0, 20.0],
    "y_bins": [5.0, 10.0],
    "cells": [[0.1, 0.2]],
    "max_amp": 0.2,
}


@pytest.mark.parametrize(
    ("typed_dict", "payload"),
    [
        (
            PeakTableRow,
            {
                "rank": 1,
                "frequency_hz": 12.0,
                "order_label": "1.0x",
                "max_intensity_db": 22.0,
                "median_intensity_db": 20.0,
                "p95_intensity_db": 21.0,
                "run_noise_baseline_db": 8.0,
                "median_vs_run_noise_ratio": 2.5,
                "p95_vs_run_noise_ratio": 2.7,
                "strength_floor_db": 7.0,
                "strength_db": 19.0,
                "presence_ratio": 0.8,
                "burstiness": 0.1,
                "persistence_score": 0.9,
                "suspected_source": "wheel/tire",
                "peak_classification": "persistent",
                "typical_speed_band": "50-80 km/h",
                "unexpected": "drop-me",
            },
        ),
        (
            MatchedPoint,
            {
                "t_s": 1.0,
                "matched_hz": 12.0,
                "unexpected": "drop-me",
            },
        ),
        (
            PhaseEvidence,
            {
                "cruise_fraction": 0.5,
                "phases_detected": ["cruise"],
                "unexpected": "drop-me",
            },
        ),
        (
            LocationHotspotPayload,
            {
                "dominance_ratio": 0.8,
                "top_location": "front-left",
                "unexpected": "drop-me",
            },
        ),
        (
            FindingEvidenceMetrics,
            {
                "match_rate": 0.7,
                "vibration_strength_db": 21.0,
                "unexpected": "drop-me",
            },
        ),
        (
            SpectrogramResult,
            {
                **_SPECTROGRAM,
                "unexpected": "drop-me",
            },
        ),
        (
            PlotDataResult,
            {
                "vib_magnitude": [(0.0, 1.0, "front-left")],
                "dominant_freq": [(0.0, 12.0)],
                "amp_vs_speed": [(50.0, 0.2)],
                "amp_vs_phase": [],
                "matched_amp_vs_speed": [],
                "freq_vs_speed_by_finding": [],
                "steady_speed_distribution": None,
                "fft_spectrum": [(12.0, 0.2)],
                "fft_spectrum_raw": [(12.0, 0.2)],
                "peaks_spectrogram": _SPECTROGRAM,
                "peaks_spectrogram_raw": _SPECTROGRAM,
                "peaks_table": [],
                "phase_segments": [],
                "phase_boundaries": [],
                "unexpected": "drop-me",
            },
        ),
    ],
)
def test_analysis_view_typed_dicts_ignore_undocumented_fields(
    typed_dict: Any,
    payload: dict[str, Any],
) -> None:
    validated = TypeAdapter(typed_dict).validate_python(payload)

    assert "unexpected" not in validated
