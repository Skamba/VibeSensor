"""Tests for serializing location-intensity summary rows into payload dictionaries."""

from __future__ import annotations

from vibesensor.domain import (
    LocationIntensitySummary,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
)
from vibesensor.shared.boundaries.summary_serialization._location_intensity import (
    serialize_location_intensity_rows,
)


def test_serialize_location_intensity_rows_projects_populated_row() -> None:
    payload = serialize_location_intensity_rows(
        [
            LocationIntensitySummary(
                location="rear-left",
                partial_coverage=True,
                sample_count=8,
                sample_coverage_ratio=0.75,
                sample_coverage_warning=True,
                usable_sample_count=6,
                usable_sample_coverage_ratio=0.50,
                usable_sample_coverage_warning=True,
                mean_intensity_db=11.5,
                p50_intensity_db=10.0,
                p95_intensity_db=18.0,
                max_intensity_db=22.0,
                dropped_frames_delta=2.0,
                queue_overflow_drops_delta=1.0,
                strength_bucket_distribution=StrengthBucketDistribution(
                    total=8,
                    counts={"l0": 2, "l1": 6},
                    percent_time_l0=25.0,
                    percent_time_l1=75.0,
                ),
                phase_intensity={
                    "cruise": PhaseIntensitySummary(
                        count=3,
                        mean_intensity_db=12.0,
                        max_intensity_db=18.0,
                    )
                },
            )
        ]
    )

    assert payload == [
        {
            "location": "rear-left",
            "partial_coverage": True,
            "sample_count": 8,
            "sample_coverage_ratio": 0.75,
            "sample_coverage_warning": True,
            "usable_sample_count": 6,
            "usable_sample_coverage_ratio": 0.5,
            "usable_sample_coverage_warning": True,
            "mean_intensity_db": 11.5,
            "p50_intensity_db": 10.0,
            "p95_intensity_db": 18.0,
            "max_intensity_db": 22.0,
            "dropped_frames_delta": 2.0,
            "queue_overflow_drops_delta": 1.0,
            "strength_bucket_distribution": {
                "total": 8,
                "counts": {"l0": 2, "l1": 6},
                "percent_time_l0": 25.0,
                "percent_time_l1": 75.0,
                "percent_time_l2": 0.0,
                "percent_time_l3": 0.0,
                "percent_time_l4": 0.0,
                "percent_time_l5": 0.0,
            },
            "phase_intensity": {
                "cruise": {
                    "count": 3,
                    "mean_intensity_db": 12.0,
                    "max_intensity_db": 18.0,
                }
            },
        }
    ]


def test_serialize_location_intensity_rows_projects_sparse_row_defaults() -> None:
    payload = serialize_location_intensity_rows([LocationIntensitySummary(location="front-left")])

    assert payload == [
        {
            "location": "front-left",
            "partial_coverage": False,
            "sample_count": 0,
            "sample_coverage_ratio": 0.0,
            "sample_coverage_warning": False,
            "usable_sample_count": None,
            "usable_sample_coverage_ratio": None,
            "usable_sample_coverage_warning": None,
            "mean_intensity_db": None,
            "p50_intensity_db": None,
            "p95_intensity_db": None,
            "max_intensity_db": None,
            "dropped_frames_delta": None,
            "queue_overflow_drops_delta": None,
            "strength_bucket_distribution": {
                "total": 0,
                "counts": {},
                "percent_time_l0": 0.0,
                "percent_time_l1": 0.0,
                "percent_time_l2": 0.0,
                "percent_time_l3": 0.0,
                "percent_time_l4": 0.0,
                "percent_time_l5": 0.0,
            },
            "phase_intensity": None,
        }
    ]
