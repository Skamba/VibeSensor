"""Rendered PDF per verdict variant: pages, the texts a reader looks for, no stray placeholders."""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from io import BytesIO
from itertools import combinations
from typing import Any

import pytest
from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS
from test_support.report_rendering import report_pdf_for
from test_support.synthetic_samples import make_fault_samples, make_noise_samples

from vibesensor.report import pdf as report_pdf
from vibesensor.report.view_model import CarDiagram, DiagramMarker

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


@pytest.mark.parametrize(
    ("lang", "check_text", "summaries_clause"),
    [
        (
            "en",
            "The raw capture did not cover the whole run",
            "those moments were analyzed from the stored summaries",
        ),
        (
            "nl",
            "De ruwe opname dekte niet de hele meting",
            "die momenten zijn uit de opgeslagen samenvattingen geanalyseerd",
        ),
    ],
)
def test_incomplete_raw_capture_is_stated_once(
    lang: str, check_text: str, summaries_clause: str
) -> None:
    """The frame-integrity row already says it; the matching warning line is not repeated."""
    summary = _passing(_WHEEL)
    for check in summary["run_suitability"]:
        if check["check_key"] == "SUITABILITY_CHECK_FRAME_INTEGRITY":
            check["state"] = "warn"
            check["explanation"] = {
                "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_REPLAY_WARN",
                "total_dropped": 0,
                "total_overflow": 0,
                "replay_incomplete": 1,
                "replay_partial": 152,
                "replay_missing": 0,
                "replay_gaps": 8,
                "replay_overlaps": 11,
            }
    summary["warnings"] = [
        {
            "code": "raw_replay_coverage_incomplete",
            "severity": "warn",
            "applies_to": "raw_replay",
            "title": {"_i18n_key": "RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_TITLE"},
        }
    ]

    quality_page = " ".join(_pages(report_pdf_for(summary, lang=lang))[2].split())

    assert check_text in quality_page
    assert quality_page.count(summaries_clause) == 1


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


_REAR_CLUSTER = (
    "rear_left_seat",
    "rear_center_seat",
    "rear_right_seat",
    "rear_subframe",
    "trunk",
    "rear_left_wheel",
    "rear_right_wheel",
)


def _diagram_label_boxes(codes: Sequence[str]) -> list[tuple[str, float, float, float, float]]:
    """Draw the car diagram with a sensor at each of *codes* and read back each label's box.

    The boxes come from the text the PDF draws (its position, font and size),
    with the widest level a label shows and markers of every size side by side.
    """
    markers = tuple(
        DiagramMarker(
            code=code,
            label=code,
            value=f"{1000 + index} mg",
            ratio=(index % 3) / 2,
            strongest=not index,
        )
        for index, code in enumerate(codes)
    )
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(70 * report_pdf.MM, 120 * report_pdf.MM))
    report_pdf._car_diagram(
        canvas,
        CarDiagram(zone=None, markers=markers, front_label="FRONT"),
        4 * report_pdf.MM,
        116 * report_pdf.MM,
        62 * report_pdf.MM,
        112 * report_pdf.MM,
    )
    canvas.save()
    boxes: list[tuple[str, float, float, float, float]] = []

    def visit(text: str, cm: list[float], tm: list[float], font: Any, size: float) -> None:
        if not text.strip().endswith("mg"):
            return
        name = str(font["/BaseFont"]).lstrip("/")
        x, y = tm[4] * cm[0] + cm[4], tm[5] * cm[3] + cm[5]
        width = stringWidth(text.strip(), name, size)
        # Digits reach from the baseline to the cap height.
        boxes.append((text.strip(), x, y, x + width, y + 0.72 * size))

    PdfReader(buffer).pages[0].extract_text(visitor_text=visit)
    return boxes


def _overlapping(boxes: list[tuple[str, float, float, float, float]]) -> list[tuple[str, str]]:
    return [
        (a[0], b[0])
        for index, a in enumerate(boxes)
        for b in boxes[index + 1 :]
        if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]
    ]


@pytest.mark.parametrize(
    "codes",
    [
        tuple(report_pdf._POSITIONS),
        *(
            subset
            for size in range(2, len(_REAR_CLUSTER) + 1)
            for subset in combinations(_REAR_CLUSTER, size)
        ),
    ],
    ids=lambda codes: "+".join(code.removesuffix("_seat") for code in codes),
)
def test_diagram_labels_never_overlap(codes: tuple[str, ...]) -> None:
    boxes = _diagram_label_boxes(codes)
    assert len(boxes) == len(codes)
    assert _overlapping(boxes) == []


def test_diagram_leaders_pass_no_other_marker() -> None:
    """Each mix of the centre-line markers, with every side marker or none, all at their largest."""
    width, height = 62.0, 112.0
    body_w = width * 0.52
    body_x0 = (width - body_w) / 2
    centre = [code for code, (nx, _ny) in report_pdf._POSITIONS.items() if nx == 0.5]
    sides = [code for code in report_pdf._POSITIONS if code not in centre]
    for size in range(1, len(centre) + 1):
        for chosen in combinations(centre, size):
            for codes in (chosen, (*chosen, *sides)):
                circles = {
                    code: (
                        body_x0 + report_pdf._POSITIONS[code][0] * body_w,
                        9 + report_pdf._POSITIONS[code][1] * (height - 18),
                        4.0,
                    )
                    for code in codes
                }
                labels = report_pdf._diagram_labels(
                    circles,
                    body_x0=body_x0,
                    body_x1=body_x0 + body_w,
                    pitch=7 * 1.3 / report_pdf.MM,
                    low=7.0,
                    high=height - 2.0,
                )
                for code, label in labels.items():
                    leader = (circles[code][:2], (label.x, label.y))
                    assert not label.leader or not any(
                        report_pdf._crosses(*leader, circles[other])
                        for other in codes
                        if other != code
                    ), (codes, code)
