"""PDF report appendix section builders."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..report_analysis import _as_float
from .pdf_helpers import (
    confidence_pill_html,
    human_amp_text,
    human_finding_title,
    human_frequency_text,
    human_list,
    human_source,
    ptext,
    req_text,
    styled_table,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def build_sensor_stats(
    *,
    summary: dict[str, object],
    story: list[object],
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    style_h2: Any,
    style_note: Any,
    style_small: Any,
) -> None:
    from reportlab.platypus import PageBreak, Paragraph

    sensor_stats_rows = [
        row for row in summary.get("sensor_intensity_by_location", []) if isinstance(row, dict)
    ]
    story.extend(
        [PageBreak(), Paragraph(text_fn("Sensor statistics", "Sensorstatistieken"), style_h2)]
    )
    if sensor_stats_rows:
        stat_table_rows = [
            [
                text_fn("Location", "Locatie"),
                text_fn("Samples", "Samples"),
                "P50 (dB)",
                "P95 (dB)",
                text_fn("Max (dB)", "Max (dB)"),
                text_fn("Dropped Δ", "Verlies Δ"),
                text_fn("Overflow Δ", "Overflow Δ"),
                text_fn("L1-L5 (%)", "L1-L5 (%)"),
            ]
        ]
        for row in sensor_stats_rows:
            bucket_dist = (
                row.get("strength_bucket_distribution", {})
                if isinstance(row.get("strength_bucket_distribution"), dict)
                else {}
            )
            bucket_pct = "/".join(
                f"{(_as_float(bucket_dist.get(f'percent_time_l{idx}')) or 0.0):.0f}"
                for idx in range(1, 6)
            )
            stat_table_rows.append(
                [
                    str(row.get("location") or tr("UNKNOWN")),
                    str(int(_as_float(row.get("sample_count") or row.get("samples")) or 0)),
                    f"{(_as_float(row.get('p50_intensity_db')) or 0.0):.1f}",
                    f"{(_as_float(row.get('p95_intensity_db')) or 0.0):.1f}",
                    f"{(_as_float(row.get('max_intensity_db')) or 0.0):.1f}",
                    str(int(_as_float(row.get("dropped_frames_delta")) or 0)),
                    str(int(_as_float(row.get("queue_overflow_drops_delta")) or 0)),
                    bucket_pct,
                ]
            )
        story.append(
            styled_table(
                stat_table_rows,
                col_widths=[130, 56, 70, 70, 70, 70, 70, 78],
                repeat_rows=1,
            )
        )
        story.append(
            Paragraph(
                text_fn(
                    "L1-L5 shows approximate time share per severity strength bucket.",
                    "L1-L5 toont de benaderde tijdsverdeling per ernstniveau.",
                ),
                style_small,
            )
        )
    else:
        story.append(Paragraph(tr("NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND"), style_note))


def build_speed_analysis(
    *,
    summary: dict[str, object],
    story: list[object],
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    lang: str,
    style_h2: Any,
    style_h3: Any,
    style_body: Any,
    style_note: Any,
    steady_speed: bool,
    plots: dict[str, object],
) -> None:
    from reportlab.platypus import PageBreak, Paragraph

    story.extend([PageBreak(), Paragraph(tr("SPEED_BINNED_ANALYSIS"), style_h2)])
    if steady_speed:
        dist = (
            plots.get("steady_speed_distribution", {})
            if isinstance(plots.get("steady_speed_distribution"), dict)
            else {}
        )
        story.extend(
            [
                Paragraph(
                    text_fn("Amplitude at steady speed", "Amplitude bij constante snelheid"),
                    style_h3,
                ),
                styled_table(
                    [
                        [
                            text_fn("Percentile", "Percentiel"),
                            text_fn("Amplitude (g)", "Amplitude (g)"),
                        ],
                        ["P10", f"{(_as_float(dist.get('p10')) or 0.0):.4f}"],
                        ["P50", f"{(_as_float(dist.get('p50')) or 0.0):.4f}"],
                        ["P90", f"{(_as_float(dist.get('p90')) or 0.0):.4f}"],
                        ["P95", f"{(_as_float(dist.get('p95')) or 0.0):.4f}"],
                    ],
                    col_widths=[140, 160],
                ),
                Paragraph(
                    text_fn(
                        "Speed variation is too small to validate tracking"
                        " across speed; repeat with a 20-30 km/h sweep.",
                        "Snelheidsvariatie is te klein om tracking over snelheid"
                        " te valideren; herhaal met een sweep van 20-30 km/u.",
                    ),
                    style_note,
                ),
            ]
        )
    else:
        skipped_reason = summary.get("speed_breakdown_skipped_reason")
        if skipped_reason:
            story.append(Paragraph(str(skipped_reason), style_body))
        else:
            speed_rows = [
                [tr("SPEED_RANGE"), tr("SAMPLES"), tr("MEAN_AMPLITUDE_G"), tr("MAX_AMPLITUDE_G")]
            ]
            for row in summary.get("speed_breakdown", []):
                if not isinstance(row, dict):
                    continue
                speed_rows.append(
                    [
                        str(row.get("speed_range", "")),
                        str(int(_as_float(row.get("count")) or 0)),
                        req_text(
                            row.get("mean_vibration_strength_db"),
                            "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE",
                            tr=tr,
                            lang=lang,
                        ),
                        req_text(
                            row.get("max_vibration_strength_db"),
                            "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE",
                            tr=tr,
                            lang=lang,
                        ),
                    ]
                )
            if len(speed_rows) == 1:
                speed_rows.append(
                    [
                        tr("MISSING_2"),
                        "0",
                        tr("MISSING_SPEED_BINS_UNAVAILABLE"),
                        tr("MISSING_SPEED_BINS_UNAVAILABLE"),
                    ]
                )
            story.append(styled_table(speed_rows, col_widths=[130, 90, 140, 140]))


def build_data_quality(
    *,
    summary: dict[str, object],
    story: list[object],
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    lang: str,
    style_h2: Any,
    style_h3: Any,
    style_body: Any,
    quality: dict[str, object],
    run_suitability: list[dict[str, object]],
) -> None:
    from reportlab.platypus import PageBreak, Paragraph

    required_missing = quality.get("required_missing_pct", {}) if isinstance(quality, dict) else {}
    speed_cov = quality.get("speed_coverage", {}) if isinstance(quality, dict) else {}
    accel_sanity = quality.get("accel_sanity", {}) if isinstance(quality, dict) else {}
    outliers = quality.get("outliers", {}) if isinstance(quality, dict) else {}

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_A_DATA_QUALITY_CHECKS"), style_h2)])
    if run_suitability:
        suit_rows = [
            [
                text_fn("Check", "Controle"),
                text_fn("State", "Status"),
                text_fn("Explanation", "Toelichting"),
            ]
        ]
        for item in run_suitability:
            state = str(item.get("state") or "warn")
            suit_rows.append(
                [str(item.get("check") or ""), state, str(item.get("explanation") or "")]
            )
        story.extend(
            [
                Paragraph(text_fn("Run suitability", "Geschiktheid van de run"), style_h3),
                styled_table(suit_rows, col_widths=[190, 100, 470]),
            ]
        )
    missing_rows = [[tr("REQUIRED_COLUMN"), tr("MISSING")]]
    for col_name in ("t_s", "speed_kmh", "accel_x_g", "accel_y_g", "accel_z_g"):
        pct = _as_float(required_missing.get(col_name))
        missing_text = req_text(None, "CONSEQUENCE_QUALITY_METRIC_UNAVAILABLE", tr=tr, lang=lang)
        missing_rows.append([col_name, f"{pct:.1f}%" if pct is not None else missing_text])
    story.append(styled_table(missing_rows, col_widths=[300, 120]))

    speed_note = tr(
        "SPEED_COVERAGE_LINE",
        non_null_pct=f"{_as_float(speed_cov.get('non_null_pct')) or 0.0:.1f}",
        min_kmh=req_text(
            speed_cov.get("min_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE", tr=tr, lang=lang
        ),
        max_kmh=req_text(
            speed_cov.get("max_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE", tr=tr, lang=lang
        ),
    )
    story.append(Paragraph(speed_note, style_body))

    sanity_rows = [
        [tr("AXIS"), tr("MEAN_G"), tr("VARIANCE_G_2")],
        [
            "X",
            req_text(
                accel_sanity.get("x_mean_g"),
                "CONSEQUENCE_MEAN_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
            req_text(
                accel_sanity.get("x_variance_g2"),
                "CONSEQUENCE_VARIANCE_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            "Y",
            req_text(
                accel_sanity.get("y_mean_g"),
                "CONSEQUENCE_MEAN_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
            req_text(
                accel_sanity.get("y_variance_g2"),
                "CONSEQUENCE_VARIANCE_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            "Z",
            req_text(
                accel_sanity.get("z_mean_g"),
                "CONSEQUENCE_MEAN_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
            req_text(
                accel_sanity.get("z_variance_g2"),
                "CONSEQUENCE_VARIANCE_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
        ],
    ]
    story.append(styled_table(sanity_rows, col_widths=[100, 170, 170]))

    limit_text = req_text(
        accel_sanity.get("sensor_limit_g"),
        "CONSEQUENCE_SENSOR_LIMIT_UNKNOWN",
        tr=tr,
        lang=lang,
    )
    sat_count_text = int(_as_float(accel_sanity.get("saturation_count")) or 0)
    sat_line = tr("SATURATION_CHECKS_LINE", limit=limit_text, count=sat_count_text)
    story.append(Paragraph(sat_line, style_body))

    accel_out = outliers.get("accel_magnitude_g", {}) if isinstance(outliers, dict) else {}
    amp_out = outliers.get("amplitude_metric", {}) if isinstance(outliers, dict) else {}
    outlier_text = tr(
        "OUTLIER_SUMMARY_LINE",
        accel_pct=f"{_as_float(accel_out.get('outlier_pct')) or 0.0:.1f}",
        accel_count=int(_as_float(accel_out.get("outlier_count")) or 0),
        accel_total=int(_as_float(accel_out.get("count")) or 0),
        amp_pct=f"{_as_float(amp_out.get('outlier_pct')) or 0.0:.1f}",
        amp_count=int(_as_float(amp_out.get("outlier_count")) or 0),
        amp_total=int(_as_float(amp_out.get("count")) or 0),
    )
    story.append(Paragraph(outlier_text, style_body))


def build_metadata(
    *,
    summary: dict[str, object],
    story: list[object],
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    lang: str,
    style_h2: Any,
    style_h3: Any,
) -> None:
    from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_B_FULL_RUN_METADATA"), style_h2)])
    metadata_obj = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    timing_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("START_TIME_UTC"),
            req_text(
                summary.get("start_time_utc"),
                "CONSEQUENCE_TIMELINE_ALIGNMENT_IMPOSSIBLE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("END_TIME_UTC"),
            req_text(
                summary.get("end_time_utc"),
                "CONSEQUENCE_DURATION_INFERRED_FROM_LAST_SAMPLE",
                tr=tr,
                lang=lang,
            ),
        ],
        [tr("DURATION"), str(summary.get("record_length", tr("MISSING_DURATION_UNAVAILABLE")))],
    ]
    sensor_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("SENSOR_MODEL"),
            req_text(
                summary.get("sensor_model"),
                "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("RAW_SAMPLE_RATE_HZ_LABEL"),
            req_text(
                summary.get("raw_sample_rate_hz"),
                "CONSEQUENCE_FREQUENCY_CONFIDENCE_REDUCED",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            text_fn("Acceleration Scale (g/LSB)", "Versnellingsschaal (g/LSB)"),
            req_text(
                summary.get("accel_scale_g_per_lsb"),
                "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            text_fn("Sensors used", "Gebruikte sensoren"),
            str(int(_as_float(summary.get("sensor_count_used")) or 0)),
        ],
    ]
    fft_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("FEATURE_INTERVAL_S_LABEL"),
            req_text(
                summary.get("feature_interval_s"),
                "CONSEQUENCE_TIME_DENSITY_INTERPRETATION_REDUCED",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("FFT_WINDOW_SIZE_SAMPLES_LABEL"),
            req_text(
                summary.get("fft_window_size_samples"),
                "CONSEQUENCE_SPECTRAL_RESOLUTION_UNKNOWN",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("FFT_WINDOW_TYPE_LABEL"),
            req_text(
                summary.get("fft_window_type"),
                "CONSEQUENCE_WINDOW_LEAKAGE_ASSUMPTIONS_UNKNOWN",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("PEAK_PICKER_METHOD_LABEL"),
            req_text(
                summary.get("peak_picker_method"),
                "CONSEQUENCE_PEAK_REPRODUCIBILITY_UNCLEAR",
                tr=tr,
                lang=lang,
            ),
        ],
    ]
    vehicle_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("TIRE_WIDTH_MM_LABEL"),
            req_text(
                metadata_obj.get("tire_width_mm"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("TIRE_ASPECT_PCT_LABEL"),
            req_text(
                metadata_obj.get("tire_aspect_pct"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("RIM_SIZE_IN_LABEL"),
            req_text(
                metadata_obj.get("rim_in"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("FINAL_DRIVE_RATIO_LABEL"),
            req_text(
                metadata_obj.get("final_drive_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
        ],
        [
            tr("CURRENT_GEAR_RATIO_LABEL"),
            req_text(
                metadata_obj.get("current_gear_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
                tr=tr,
                lang=lang,
            ),
        ],
    ]
    story.extend(
        [
            KeepTogether(
                [
                    Paragraph(text_fn("Timing", "Timing"), style_h3),
                    styled_table(timing_rows, col_widths=[250, 470]),
                ]
            ),
            Spacer(1, 4),
            KeepTogether(
                [
                    Paragraph(text_fn("Sensor", "Sensor"), style_h3),
                    styled_table(sensor_rows, col_widths=[250, 470]),
                ]
            ),
            Spacer(1, 4),
            KeepTogether(
                [
                    Paragraph(text_fn("FFT", "FFT"), style_h3),
                    styled_table(fft_rows, col_widths=[250, 470]),
                ]
            ),
            Spacer(1, 4),
            KeepTogether(
                [
                    Paragraph(text_fn("Vehicle", "Voertuig"), style_h3),
                    styled_table(vehicle_rows, col_widths=[250, 470]),
                ]
            ),
        ]
    )


def build_detailed_findings(
    *,
    findings: list[dict[str, object]] | object,
    story: list[object],
    tr: Callable[..., str],
    text_fn: Callable[..., str],
    lang: str,
    style_h2: Any,
    style_note: Any,
    style_table_head: Any,
) -> None:
    from functools import partial

    from reportlab.platypus import PageBreak, Paragraph

    _pt = partial(ptext, style_table_head=style_table_head, style_note=style_note)

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_C_DETAILED_FINDINGS_TABLE"), style_h2)])
    detailed_rows: list[list[object]] = [
        [
            _pt(tr("FINDING"), header=True),
            _pt(tr("LIKELY_SOURCE"), header=True),
            _pt(tr("WHY_WE_THINK_THIS"), header=True),
            _pt(tr("MATCHED_FREQUENCY_ORDER"), header=True),
            _pt(tr("AMPLITUDE_SUMMARY"), header=True),
            _pt(tr("CONFIDENCE_LABEL"), header=True),
            _pt(tr("QUICK_CHECKS"), header=True),
        ]
    ]
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            detailed_rows.append(
                [
                    _pt(human_finding_title(finding, idx, tr=tr)),
                    _pt(human_source(finding.get("suspected_source"), tr=tr)),
                    _pt(finding.get("evidence_summary", "")),
                    _pt(human_frequency_text(finding.get("frequency_hz_or_order"), tr=tr)),
                    _pt(human_amp_text(finding.get("amplitude_metric"), tr=tr, text_fn=text_fn)),
                    Paragraph(
                        confidence_pill_html(
                            _as_float(finding.get("confidence_0_to_1")) or 0.0,
                            tr=tr,
                            show_percent=True,
                        ),
                        style_note,
                    ),
                    human_list(
                        finding.get("quick_checks"),
                        tr=tr,
                        style_table_head=style_table_head,
                        style_note=style_note,
                    ),
                ]
            )
    else:
        detailed_rows.append(
            [
                _pt(tr("NO_DIAGNOSTIC_FINDINGS")),
                _pt(tr("UNKNOWN")),
                _pt(tr("NO_FINDINGS_WERE_GENERATED_FROM_THE_AVAILABLE_DATA")),
                _pt(tr("REFERENCE_NOT_AVAILABLE")),
                _pt(tr("NOT_AVAILABLE")),
                _pt("0%"),
                _pt(tr("RECORD_ADDITIONAL_DATA")),
            ]
        )
    story.append(
        styled_table(detailed_rows, col_widths=[90, 84, 230, 118, 166, 58, 70], repeat_rows=1)
    )
