from __future__ import annotations

from _test_helpers import assert_summary_sections, assert_top_cause_contract, extract_pdf_text
from builders import make_sample as make_sample
from builders import standard_metadata as standard_metadata
from builders import wheel_hz as wheel_hz

from vibesensor.analysis import map_summary
from vibesensor.analysis.summary import summarize_run_data

ALL_SENSORS = ["front-left", "front-right", "rear-left", "rear-right"]