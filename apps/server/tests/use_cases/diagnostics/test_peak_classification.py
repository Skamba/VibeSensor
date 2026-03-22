from __future__ import annotations

import pytest

from vibesensor.use_cases.diagnostics.peak_classification import classify_peak_type


class TestClassifyPeakType:
    @pytest.mark.parametrize(
        ("presence_ratio", "burstiness", "snr", "spatial_uniformity", "expected"),
        [
            (0.5, 2.0, 1.0, None, "baseline_noise"),
            (0.05, 2.0, 5.0, None, "transient"),
            (0.30, 6.0, 5.0, None, "transient"),
            (0.50, 2.0, 5.0, None, "patterned"),
            (0.25, 3.5, 5.0, None, "persistent"),
            (0.70, 1.5, 5.0, 0.90, "baseline_noise"),
        ],
    )
    def test_classification_cases(
        self,
        presence_ratio: float,
        burstiness: float,
        snr: float,
        spatial_uniformity: float | None,
        expected: str,
    ) -> None:
        assert (
            classify_peak_type(
                presence_ratio,
                burstiness,
                snr=snr,
                spatial_uniformity=spatial_uniformity,
            )
            == expected
        )
