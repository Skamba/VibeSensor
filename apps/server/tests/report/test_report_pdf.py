"""Rendered PDF per verdict variant: pages, the texts a reader looks for, no stray placeholders."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from typing import Any

import pytest
from pypdf import PdfReader
from test_support import ALL_WHEEL_SENSORS, make_fault_samples, make_noise_samples
from test_support.analysis import run_analysis
from test_support.report_rendering import report_pdf_for

from vibesensor.report import pdf as report_pdf

_FORBIDDEN = ("None", "nan", "{", "}", "_i18n_key")


def _pages(pdf: bytes) -> list[str]:
    return [page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages]


def _passing(summary: dict[str, Any]) -> dict[str, Any]:
    summary = deepcopy(summary)
    summary["warnings"] = []
    for check in summary["run_suitability"]:
        check["state"] = "pass"
    return summary


_WHEEL = run_analysis(make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS))
_HEALTHY = run_analysis(make_noise_samples(sensors=ALL_WHEEL_SENSORS, n_samples=30))


def _variant(**diagnosis: Any) -> dict[str, Any]:
    summary = deepcopy(_WHEEL)
    summary["diagnosis"].update(diagnosis)
    return summary


_CASES: dict[str, tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]] = {
    "healthy": (
        _HEALTHY,
        ("No significant vibration found", "What this test covered", "Not covered"),
        ("No vibration that follows wheel, propshaft or engine speed was found.",),
    ),
    "wheel": (
        _WHEEL,
        ("Likely cause: a wheel or tire problem at the front-left wheel", "Check the fix"),
        ("T1 - once per wheel turn", "Road-force all four", "Amplitude at T1 per location"),
    ),
    "driveline": (
        _variant(
            source="driveline", order_code="P1", zone="rear_axle", confidence_level="moderate"
        ),
        ("near the rear axle", "CHEAP CHECK FIRST", "shift to neutral"),
        ("Measure the driveline working angles.",),
    ),
    "engine": (
        _variant(source="engine", order_code="E2", zone="engine_bay", confidence_level="strong"),
        ("Likely cause: the engine or its mounts (the engine bay)",),
        ("Inspect the engine and gearbox mounts.",),
    ),
    "weak": (
        _variant(
            verdict="weak_evidence",
            confidence_level="weak",
            zone="front_axle",
            weak_reasons=["spread_across_locations"],
        ),
        ("Not enough evidence to name a cause", "Best guess, not confirmed", "Record the test"),
        ("Don't replace parts based on this report alone",),
    ),
}


@pytest.mark.parametrize("variant", sorted(_CASES))
def test_variant_pages_carry_owner_and_workshop_text(variant: str) -> None:
    summary, owner_texts, workshop_texts = _CASES[variant]
    pages = _pages(report_pdf_for(summary))

    assert len(pages) in (2, 3)
    owner_page = " ".join(pages[0].split())
    workshop_page = " ".join(pages[1].split())
    for text in owner_texts:
        assert text in owner_page, (text, owner_page)
    for text in workshop_texts:
        assert text in workshop_page, (text, workshop_page)
    assert "For the workshop" in workshop_page
    assert "Test conditions" in workshop_page
    for page in pages:
        for token in _FORBIDDEN:
            assert token not in page.split(), (token, page)
    assert "%" not in owner_page


def test_all_checks_passed_collapses_quality_into_the_footer() -> None:
    pages = _pages(report_pdf_for(_passing(_WHEEL)))

    assert len(pages) == 2
    assert "All data checks passed" in pages[1]
    assert "Page 2 of 2" in pages[1]


def test_a_quality_warning_adds_the_data_quality_page() -> None:
    summary = _passing(_WHEEL)
    summary["warnings"] = [
        {
            "code": "raw_replay_coverage_incomplete",
            "severity": "warn",
            "applies_to": "raw_capture",
            "title": {"_i18n_key": "RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_TITLE"},
        }
    ]
    pages = _pages(report_pdf_for(summary))

    assert len(pages) == 3
    assert "Data quality and traceability" in pages[2]
    assert "Part of the raw sensor data was missing" in " ".join(pages[2].split())
    assert "Page 3 of 3" in pages[2]


def test_dutch_pdf_is_dutch() -> None:
    pages = _pages(report_pdf_for(_WHEEL, lang="nl"))
    text = " ".join(" ".join(pages).split())

    assert "VibeSensor-trillingsrapport" in text
    assert "Waarschijnlijke oorzaak" in text
    assert "Voor de werkplaats" in text
    assert "Likely cause" not in text


def test_charts_move_to_page_three_when_the_workshop_page_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pretend the charts need more room than page 2 has left.
    monkeypatch.setattr(report_pdf, "_CHART_MIN_H", 10_000.0)

    pages = _pages(report_pdf_for(_passing(_WHEEL)))

    assert len(pages) == 3
    assert "What to ask the shop" in pages[1]
    assert "Recurring peaks at" not in pages[1]
    assert "Recurring peaks at" in pages[2]
    assert "All data checks passed" in pages[2]
    assert "Data quality and traceability" not in pages[2]
