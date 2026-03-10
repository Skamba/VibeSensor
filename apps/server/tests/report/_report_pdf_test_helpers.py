from __future__ import annotations

import re
from io import BytesIO

from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from test_support.report_helpers import RUN_END, suitability_by_key, write_jsonl
from test_support.report_helpers import report_run_metadata as run_metadata
from test_support.report_helpers import report_sample as base_sample

from vibesensor import __version__
from vibesensor.analysis import map_summary, summarize_log
from vibesensor.constants import KMH_TO_MPS
from vibesensor.report.pdf_diagram_render import car_location_diagram
from vibesensor.report.pdf_engine import build_report_pdf
from vibesensor.report.pdf_page1 import _draw_system_card
from vibesensor.report.report_data import PartSuggestion, SystemFindingCard

__all__ = [
    "KMH_TO_MPS",
    "RUN_END",
    "BytesIO",
    "Canvas",
    "PartSuggestion",
    "PdfReader",
    "SystemFindingCard",
    "__version__",
    "_draw_system_card",
    "assert_pdf_contains",
    "build_report_pdf",
    "car_location_diagram",
    "extract_media_box",
    "map_summary",
    "run_metadata",
    "sample",
    "suitability_by_key",
    "summarize_log",
    "write_jsonl",
]


def sample(
    idx: int,
    *,
    speed_kmh: float | None,
    dominant_freq_hz: float,
    peak_amp_g: float,
) -> dict:
    return base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
        add_index_accel_offset=True,
        include_secondary_peak=True,
    )


def assert_pdf_contains(pdf_bytes: bytes, text: str) -> None:
    assert text.encode("latin-1", errors="ignore") in pdf_bytes


def extract_media_box(pdf_bytes: bytes) -> tuple[float, float, float, float]:
    text = pdf_bytes.decode("latin-1", errors="ignore")
    match = re.search(
        r"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        text,
    )
    assert match is not None
    return tuple(float(match.group(idx)) for idx in range(1, 5))
