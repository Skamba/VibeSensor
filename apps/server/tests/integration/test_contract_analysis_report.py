"""Contract bridge tests: Analysis -> Report boundary.

The output of ``summarize_run_data()`` must build a report view and render a
PDF for representative scenarios, and the report must name the same verdict
as the persisted diagnosis. Fast, deterministic, standard CI.
"""

from __future__ import annotations

import pytest
from test_support import (
    ALL_WHEEL_SENSORS,
    make_fault_samples,
    make_noise_samples,
    standard_metadata,
)
from test_support.report_rendering import report_pdf_for, report_view_for

from vibesensor.analysis.summarize import summarize_run_data

pytestmark = pytest.mark.smoke


def _make_small_dataset() -> tuple[dict, list[dict]]:
    """Return a minimal (metadata, samples) pair with a detectable fault."""
    meta = standard_metadata(language="en")
    samples: list[dict] = []
    samples.extend(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=15, speed_kmh=60.0))
    samples.extend(
        make_fault_samples(
            fault_sensor="front-left",
            sensors=ALL_WHEEL_SENSORS,
            speed_kmh=80.0,
            n_samples=20,
        )
    )
    return meta, samples


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("meta", "samples", "lang", "expect_top_cause_mapping"),
    [
        pytest.param(*_make_small_dataset(), "en", True, id="fault-en"),
        pytest.param(
            standard_metadata(language="en"),
            make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30, speed_kmh=60.0),
            "en",
            False,
            id="noise-en",
        ),
        pytest.param(
            standard_metadata(language="nl"),
            make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=20, speed_kmh=60.0),
            "nl",
            False,
            id="noise-nl",
        ),
    ],
)
def test_analysis_to_report_bridge_scenarios(
    meta: dict,
    samples: list[dict],
    lang: str,
    expect_top_cause_mapping: bool,
) -> None:
    """Analysis output builds a report view and PDF that name the persisted verdict."""
    summary = summarize_run_data(meta, samples, lang=lang)
    view = report_view_for(summary, lang=lang)
    diagnosis = summary["diagnosis"]

    assert view.lang == lang
    assert view.owner.verdict == diagnosis["verdict"]
    assert view.owner.level == diagnosis["confidence_level"]
    assert view.mechanic.amplitudes
    assert report_pdf_for(summary, lang=lang).startswith(b"%PDF")

    if not expect_top_cause_mapping:
        assert diagnosis["verdict"] == "no_fault"
        return

    assert diagnosis["verdict"] == "fault"
    assert diagnosis["finding_id"] == summary["top_causes"][0]["finding_id"]
    assert diagnosis["source"] == summary["top_causes"][0]["suspected_source"]
    assert view.mechanic.worksheet[0].diagnosed
