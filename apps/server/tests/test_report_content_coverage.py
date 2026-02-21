from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from vibesensor.constants import KMH_TO_MPS
from vibesensor.report import confidence_label, pdf_builder, select_top_causes, summarize_log
from vibesensor.report.pdf_builder import build_report_pdf
from vibesensor.report.report_data import PatternEvidence, ReportTemplateData

_I18N_JSON = Path(__file__).resolve().parent.parent / "data" / "report_i18n.json"

# -- Fixtures reused from test_reports.py pattern ----------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def _run_metadata(run_id: str = "run-01", **kwargs) -> dict:
    defaults = {
        "record_type": "run_metadata",
        "schema_version": "v2-jsonl",
        "run_id": run_id,
        "start_time_utc": "2026-02-15T12:00:00+00:00",
        "end_time_utc": "2026-02-15T12:01:00+00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 0.5,
        "fft_window_size_samples": 2048,
        "fft_window_type": "hann",
        "peak_picker_method": "max_peak_amp_across_axes",
        "accel_scale_g_per_lsb": 1.0 / 256.0,
        "units": {
            "t_s": "s",
            "speed_kmh": "km/h",
            "accel_x_g": "g",
            "accel_y_g": "g",
            "accel_z_g": "g",
            "vibration_strength_db": "dB",
        },
        "amplitude_definitions": {
            "vibration_strength_db": {
                "statistic": "Peak band RMS vs noise floor",
                "units": "dB",
                "definition": "20*log10((peak_band_rms + eps) / (floor + eps))",
            }
        },
    }
    defaults.update(kwargs)
    defaults.setdefault("incomplete_for_order_analysis", defaults.get("raw_sample_rate_hz") is None)
    return defaults


def _sample(idx: int, *, speed_kmh: float, dominant_freq_hz: float, peak_amp_g: float) -> dict:
    return {
        "record_type": "sample",
        "schema_version": "v2-jsonl",
        "run_id": "run-01",
        "timestamp_utc": f"2026-02-15T12:00:{idx:02d}+00:00",
        "t_s": idx * 0.5,
        "client_id": "c1",
        "client_name": "front-left wheel",
        "speed_kmh": speed_kmh,
        "gps_speed_kmh": speed_kmh,
        "engine_rpm": None,
        "gear": None,
        "accel_x_g": 0.03 + (idx * 0.0005),
        "accel_y_g": 0.02 + (idx * 0.0003),
        "accel_z_g": 0.01 + (idx * 0.0002),
        "dominant_freq_hz": dominant_freq_hz,
        "dominant_axis": "x",
        "top_peaks": [
            {
                "hz": dominant_freq_hz,
                "amp": peak_amp_g,
                "vibration_strength_db": 22.0,
                "strength_bucket": "l2",
            },
        ],
        "vibration_strength_db": 22.0,
        "strength_bucket": "l2",
    }


def _make_run_jsonl(tmp_path: Path, *, tire_circumference_m: float = 2.20) -> Path:
    run_path = tmp_path / "run_content.jsonl"
    records: list[dict] = [_run_metadata(tire_circumference_m=tire_circumference_m)]
    for idx in range(30):
        speed = 40 + idx
        wheel_hz = (speed * KMH_TO_MPS) / tire_circumference_m
        records.append(
            _sample(idx, speed_kmh=float(speed), dominant_freq_hz=wheel_hz, peak_amp_g=0.09)
        )
    records.append({"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"})
    _write_jsonl(run_path, records)
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


def test_select_top_causes_excludes_informational_transient_findings() -> None:
    findings = [
        {
            "finding_id": "F007",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence_0_to_1": 0.22,
            "frequency_hz_or_order": "92.0 Hz",
        }
    ]
    causes = select_top_causes(findings)
    assert causes == []


def test_select_top_causes_ignores_info_even_with_high_confidence() -> None:
    findings = [
        {
            "finding_id": "F008",
            "severity": "info",
            "suspected_source": "transient_impact",
            "peak_classification": "transient",
            "confidence_0_to_1": 0.99,
            "frequency_hz_or_order": "120.0 Hz",
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


# -- confidence_label --------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected_key, expected_tone",
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
    "PEAK_AMP_G",
    "STRENGTH_DB",
]


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def test_pdf_section_headings_present(tmp_path: Path) -> None:
    run_path = _make_run_jsonl(tmp_path)
    summary = summarize_log(run_path, lang="en")
    pdf = build_report_pdf(summary)
    text = _extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing = []
    for key in _SECTION_HEADING_KEYS:
        heading = i18n[key]["en"]
        if heading not in text:
            missing.append(f"{key} ({heading!r})")
    assert missing == [], f"Missing English headings in PDF: {missing}"


def test_pdf_nl_contains_dutch_headings(tmp_path: Path) -> None:
    run_path = _make_run_jsonl(tmp_path)
    summary = summarize_log(run_path, lang="nl")
    pdf = build_report_pdf(summary)
    text = _extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing = []
    for key in _SECTION_HEADING_KEYS:
        heading = i18n[key]["nl"]
        if heading not in text:
            missing.append(f"{key} ({heading!r})")
    assert missing == [], f"Missing Dutch headings in PDF: {missing}"


def test_pdf_peaks_table_includes_peak_amp_and_strength_columns(tmp_path: Path) -> None:
    run_path = _make_run_jsonl(tmp_path)
    summary = summarize_log(run_path, lang="en")
    pdf = build_report_pdf(summary)
    text = _extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    missing = []
    for key in _PEAK_TABLE_COLUMN_KEYS:
        label = i18n[key]["en"]
        if label not in text:
            missing.append(f"{key} ({label!r})")
    assert missing == [], f"Missing peak table columns in PDF: {missing}"


def test_pdf_additional_observations_heading_for_transient_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pdf_builder,
        "map_summary",
        lambda _summary: ReportTemplateData(
            title="Diagnostic worksheet",
            pattern_evidence=PatternEvidence(),
            lang="en",
        ),
    )
    monkeypatch.setattr(
        pdf_builder,
        "location_hotspots",
        lambda *_args, **_kwargs: ([], None, None, None),
    )

    summary = {"samples": [], "top_causes": []}
    summary["findings"] = [
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
    ]

    pdf = build_report_pdf(summary)
    text = _extract_pdf_text(pdf)
    i18n = json.loads(_I18N_JSON.read_text(encoding="utf-8"))
    assert i18n["ADDITIONAL_OBSERVATIONS"]["en"] in text
