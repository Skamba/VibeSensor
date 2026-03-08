from __future__ import annotations

import json
from pathlib import Path

import pytest
from _paths import SERVER_ROOT
from _report_helpers import (
    RUN_END,
    write_jsonl,
)
from _report_helpers import (
    report_run_metadata as _run_metadata,
)
from _report_helpers import (
    report_sample as _base_sample,
)
from _test_helpers import extract_pdf_text

from vibesensor.analysis import confidence_label, map_summary, select_top_causes, summarize_log
from vibesensor.constants import KMH_TO_MPS
from vibesensor.report.pdf_engine import build_report_pdf
from vibesensor.report.report_data import PatternEvidence, ReportTemplateData

_I18N_JSON = SERVER_ROOT / "data" / "report_i18n.json"

# -- Fixtures reused from test_reports.py pattern ----------------------------


def _sample(idx: int, *, speed_kmh: float, dominant_freq_hz: float, peak_amp_g: float) -> dict:
    return _base_sample(
        idx,
        speed_kmh=speed_kmh,
        dominant_freq_hz=dominant_freq_hz,
        peak_amp_g=peak_amp_g,
        add_index_accel_offset=True,
    )


def _make_run_jsonl(tmp_path: Path, *, tire_circumference_m: float = 2.20) -> Path:
    run_path = tmp_path / "run_content.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=tire_circumference_m)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * KMH_TO_MPS) / tire_circumference_m
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09)
        )
    records.append(RUN_END)
    write_jsonl(run_path, records)
    return run_path


# -- select_top_causes -------------------------------------------------------


def test_select_top_causes_groups_by_source() -> None:
    findings = [
        {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.80,
            "frequency_hz_or_order": "1x wheel order",
        },
        {
            "finding_id": "F002",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.65,
            "frequency_hz_or_order": "2x wheel order",
        },
        {
            "finding_id": "F003",
            "suspected_source": "engine",
            "confidence_0_to_1": 0.55,
            "frequency_hz_or_order": "2x engine order",
        },
    ]
    causes = select_top_causes(findings)
    sources = [c["source"] for c in causes]
    # Two wheel/tire findings should be grouped into one cause
    assert sources.count("wheel/tire") == 1
    # The wheel/tire group representative should carry both signatures
    wheel_cause = [c for c in causes if c["source"] == "wheel/tire"][0]
    assert wheel_cause["grouped_count"] == 2
    assert len(wheel_cause["signatures_observed"]) == 2


def test_select_top_causes_empty_findings() -> None:
    assert select_top_causes([]) == []


def test_select_top_causes_excludes_reference_findings() -> None:
    findings = [
        {
            "finding_id": "REF_SPEED",
            "suspected_source": "unknown",
            "confidence_0_to_1": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
        {
            "finding_id": "REF_WHEEL",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
        {
            "finding_id": "REF_ENGINE",
            "suspected_source": "engine",
            "confidence_0_to_1": 1.0,
            "frequency_hz_or_order": "reference missing",
        },
    ]
    causes = select_top_causes(findings)
    assert causes == []


@pytest.mark.parametrize(
    ("confidence", "freq_hz"),
    [
        pytest.param(0.22, "92.0 Hz", id="low_confidence"),
        pytest.param(0.99, "120.0 Hz", id="high_confidence"),
    ],
)
def test_select_top_causes_excludes_informational_transient_findings(
    confidence: float,
    freq_hz: str,
) -> None:
    findings = [
        {
            "finding_id": "F007",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence_0_to_1": confidence,
            "frequency_hz_or_order": freq_hz,
        }
    ]
    causes = select_top_causes(findings)
    assert causes == []


def test_select_top_causes_prefers_diagnostic_over_info() -> None:
    findings = [
        {
            "finding_id": "F009",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence_0_to_1": 0.99,
            "frequency_hz_or_order": "120.0 Hz",
        },
        {
            "finding_id": "F010",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.26,
            "frequency_hz_or_order": "1x wheel order",
        },
    ]
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0]["source"] == "wheel/tire"


def test_select_top_causes_prefers_cruise_phase_evidence() -> None:
    """A finding with strong cruise-phase evidence should rank above one with
    equal raw confidence but no cruise evidence."""
    findings = [
        {
            "finding_id": "F_A",
            "severity": "diagnostic",
            "suspected_source": "driveline",
            "confidence_0_to_1": 0.60,
            "frequency_hz_or_order": "3x driveshaft",
            # No phase evidence — neutral multiplier
        },
        {
            "finding_id": "F_B",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.60,
            "frequency_hz_or_order": "1x wheel order",
            # All matches were in cruise phase
            "phase_evidence": {"cruise_fraction": 1.0, "phases_detected": ["cruise"]},
        },
    ]
    causes = select_top_causes(findings)
    # Both qualify; wheel/tire (cruise dominant) should come first
    assert len(causes) == 2
    assert causes[0]["source"] == "wheel/tire"
    assert causes[1]["source"] == "driveline"


def test_select_top_causes_phase_evidence_in_output() -> None:
    """phase_evidence from the representative finding must be passed through."""
    phase_ev = {"cruise_fraction": 0.85, "phases_detected": ["cruise", "acceleration"]}
    findings = [
        {
            "finding_id": "F_C",
            "severity": "diagnostic",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.75,
            "frequency_hz_or_order": "1x wheel order",
            "phase_evidence": phase_ev,
        }
    ]
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0]["phase_evidence"] == phase_ev


def test_select_top_causes_no_phase_evidence_still_works() -> None:
    """Findings without phase_evidence should still be ranked correctly."""
    findings = [
        {
            "finding_id": "F_D",
            "severity": "diagnostic",
            "suspected_source": "engine",
            "confidence_0_to_1": 0.55,
            "frequency_hz_or_order": "2x engine order",
        }
    ]
    causes = select_top_causes(findings)
    assert len(causes) == 1
    assert causes[0]["source"] == "engine"
    assert causes[0]["phase_evidence"] is None


# -- confidence_label --------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected_key", "expected_tone"),
    [
        (0.0, "CONFIDENCE_LOW", "neutral"),
        (0.39, "CONFIDENCE_LOW", "neutral"),
        (0.40, "CONFIDENCE_MEDIUM", "warn"),
        (0.69, "CONFIDENCE_MEDIUM", "warn"),
        (0.70, "CONFIDENCE_HIGH", "success"),
        (1.0, "CONFIDENCE_HIGH", "success"),
    ],
)
def test_confidence_label_boundaries(value: float, expected_key: str, expected_tone: str) -> None:
    label_key, tone, pct_text = confidence_label(value)
    assert label_key == expected_key
    assert tone == expected_tone
    assert pct_text == f"{value * 100:.0f}%"


def test_confidence_label_negligible_strength_caps_high_to_medium() -> None:
    """High confidence + negligible strength → CONFIDENCE_MEDIUM, not CONFIDENCE_HIGH."""
    label_key, tone, _ = confidence_label(0.80, strength_band_key="negligible")
    assert label_key == "CONFIDENCE_MEDIUM"
    assert tone == "warn"


@pytest.mark.parametrize(
    ("value", "expected_key"),
    [
        pytest.param(0.55, "CONFIDENCE_MEDIUM", id="medium_stays_medium"),
        pytest.param(0.20, "CONFIDENCE_LOW", id="low_stays_low"),
    ],
)
def test_confidence_label_negligible_does_not_affect_below_high(
    value: float,
    expected_key: str,
) -> None:
    """Negligible strength does not alter labels already below high."""
    label_key, _, _ = confidence_label(value, strength_band_key="negligible")
    assert label_key == expected_key


def test_confidence_label_non_negligible_allows_high() -> None:
    """Non-negligible (or absent) strength_band_key must not prevent CONFIDENCE_HIGH."""
    for band in ("light", "moderate", "strong", "very_strong", None):
        label_key, tone, _ = confidence_label(0.80, strength_band_key=band)
        assert label_key == "CONFIDENCE_HIGH", f"Unexpected cap for strength_band_key={band!r}"
        assert tone == "success"


# -- PDF section heading coverage --------------------------------------------

_SECTION_HEADING_KEYS = [
    "DIAGNOSTIC_WORKSHEET",
    "OBSERVED_SIGNATURE",
    "SYSTEMS_WITH_FINDINGS",
    "NEXT_STEPS",
    "DATA_TRUST",
    "EVIDENCE_DIAGNOSTICS",
    "PATTERN_EVIDENCE",
    "DIAGNOSTIC_PEAKS",
]

_PEAK_TABLE_COLUMN_KEYS = [
    "PEAK_DB",
    "STRENGTH_DB",
]


@pytest.mark.parametrize(
    ("lang", "i18n_keys"),
    [
        pytest.param("en", _SECTION_HEADING_KEYS, id="en_section_headings"),
        pytest.param("nl", _SECTION_HEADING_KEYS, id="nl_section_headings"),
        pytest.param("en", _PEAK_TABLE_COLUMN_KEYS, id="en_peak_table_columns"),
    ],
)
def test_pdf_contains_i18n_labels(
    tmp_path: Path,
    lang: str,
    i18n_keys: list[str],
) -> None:
    run_path = _make_run_jsonl(tmp_path)
    summary = summarize_log(run_path, lang=lang)
    pdf = build_report_pdf(map_summary(summary))
    text = extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing = []
    for key in i18n_keys:
        label = i18n[key][lang]
        if label not in text:
            missing.append(f"{key} ({label!r})")
    assert missing == [], f"Missing {lang} labels in PDF: {missing}"


def test_pdf_additional_observations_heading_for_transient_findings() -> None:
    data = ReportTemplateData(
        title="Diagnostic worksheet",
        pattern_evidence=PatternEvidence(),
        lang="en",
        findings=[
            {
                "finding_id": "F001",
                "severity": "diagnostic",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.55,
                "frequency_hz_or_order": "1x wheel order",
            },
            {
                "finding_id": "F002",
                "severity": "info",
                "suspected_source": "transient_impact",
                "peak_classification": "transient",
                "confidence_0_to_1": 0.22,
                "frequency_hz_or_order": "95.0 Hz",
            },
        ],
    )

    pdf = build_report_pdf(data)
    text = extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    assert i18n["ADDITIONAL_OBSERVATIONS"]["en"] in text
