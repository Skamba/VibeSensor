from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from io import BytesIO
from statistics import mean

from .report_analysis import (
    SPEED_COVERAGE_MIN_PCT,
    _as_float,
    _normalize_lang,
    _required_text,
)
from .report_i18n import tr as _tr
from .report_i18n import variants as _tr_variants


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fallback_pdf(summary: dict[str, object]) -> bytes:
    lang = _normalize_lang(summary.get("lang"))
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    findings = summary.get("findings", [])

    lines = [
        _tr(lang, "VIBESENSOR_NVH_REPORT"),
        "",
        _tr(lang, "GENERATED_GENERATED", generated=generated),
        _tr(lang, "RUN_FILE_NAME", name=summary.get("file_name", "")),
        f"Run ID: {summary.get('run_id', '')}",
        _tr(lang, "ROWS_ROWS", rows=summary.get("rows", 0)),
        _tr(lang, "DURATION_DURATION_1F_S", duration=float(summary.get("duration_s", 0.0))),
        _tr(lang, "FINDINGS"),
    ]
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings[:8], start=1):
            if not isinstance(finding, dict):
                continue
            lines.append(
                f"{idx}. {finding.get('suspected_source', 'unknown')} | "
                f"{finding.get('evidence_summary', '')}"
            )
    else:
        lines.append(_tr(lang, "T_1_NO_FINDINGS_GENERATED"))

    lines = lines[:44]
    content_lines = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
    for i, line in enumerate(lines):
        safe = _pdf_escape(str(line))
        if i == 0:
            content_lines.append(f"({safe}) Tj")
        else:
            content_lines.append(f"T* ({safe}) Tj")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>".encode("ascii") + b"\nstream\n" + content + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")

    xref_start = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def _reportlab_pdf(summary: dict[str, object]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.graphics.shapes import Drawing, Line, PolyLine, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    page_size = landscape(LETTER)
    content_width = page_size[0] - 48
    lang = _normalize_lang(summary.get("lang"))

    def tr(key: str, **kwargs: object) -> str:
        return _tr(lang, key, **kwargs)

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleMain",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1f3a52"),
        spaceAfter=8,
    )
    style_h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#1f3a52"),
        spaceAfter=4,
        spaceBefore=8,
    )
    style_body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    style_note = ParagraphStyle(
        "Note",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#4f5d73"),
    )
    style_table_head = ParagraphStyle(
        "TableHead",
        parent=style_note,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.0,
        textColor=colors.HexColor("#1f3a52"),
    )
    style_h3 = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#1f3a52"),
        spaceBefore=5,
        spaceAfter=2,
    )

    def ptext(value: object, *, header: bool = False, break_underscores: bool = False) -> Paragraph:
        text = escape(str(value if value is not None else ""))
        text = text.replace("\n", "<br/>")
        if break_underscores:
            text = text.replace("_", "_<br/>")
        return Paragraph(text, style_table_head if header else style_note)

    def human_source(source: object) -> str:
        raw = str(source or "").strip().lower()
        mapping = {
            "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
            "driveline": tr("SOURCE_DRIVELINE"),
            "engine": tr("SOURCE_ENGINE"),
            "body resonance": tr("SOURCE_BODY_RESONANCE"),
            "unknown": tr("UNKNOWN"),
        }
        return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))

    def human_finding_title(finding: dict[str, object], index: int) -> str:
        fid = str(finding.get("finding_id", "")).strip().upper()
        source = human_source(finding.get("suspected_source"))
        mapping = {
            "REF_SPEED": tr("MISSING_SPEED_REFERENCE"),
            "REF_WHEEL": tr("MISSING_WHEEL_REFERENCE"),
            "REF_ENGINE": tr("MISSING_ENGINE_REFERENCE"),
            "INFO_ENGINE_REF": tr("DERIVED_ENGINE_REFERENCE"),
            "REF_SAMPLE_RATE": tr("MISSING_SAMPLE_RATE_METADATA"),
        }
        if fid in mapping:
            return mapping[fid]
        if fid.startswith("F") and fid[1:].isdigit():
            return tr("FINDING_INDEX_SOURCE", index=index, source=source)
        return tr("FINDING_INDEX_SOURCE", index=index, source=source)

    def human_frequency_text(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return tr("REFERENCE_NOT_AVAILABLE")
        lowered = raw.lower()
        missing_markers = {item.lower() for item in _tr_variants("REFERENCE_MISSING")}
        derived_markers = {item.lower() for item in _tr_variants("REFERENCE_AVAILABLE_DERIVED")}
        if lowered in missing_markers:
            return tr("REFERENCE_NOT_AVAILABLE")
        if lowered in derived_markers:
            return tr("REFERENCE_AVAILABLE_DERIVED_FROM_OTHER_MEASUREMENTS")
        return raw

    def human_amp_text(amp: object) -> str:
        if not isinstance(amp, dict):
            return tr("NOT_AVAILABLE")
        name_raw = str(amp.get("name", "")).strip()
        value = _as_float(amp.get("value"))
        units = str(amp.get("units", "")).strip()
        definition = str(amp.get("definition", "")).strip()
        if name_raw == "not_available":
            if definition:
                return f"{tr('NOT_AVAILABLE')}. {definition}"
            return tr("NOT_AVAILABLE")
        name_map = {
            "dominant_peak_amp_g": tr("DOMINANT_PEAK_AMPLITUDE"),
            "not_available": tr("NOT_AVAILABLE"),
        }
        label = name_map.get(
            name_raw,
            name_raw.replace("_", " ").title() if name_raw else tr("METRIC_LABEL"),
        )
        value_text = tr("NOT_AVAILABLE_2") if value is None else f"{value:.4f} {units}".strip()
        if definition:
            return f"{label}: {value_text}. {definition}"
        return f"{label}: {value_text}"

    def human_list(items: object) -> Paragraph:
        if not isinstance(items, list):
            return ptext(tr("NONE_LISTED"))
        cleaned = [str(v).strip() for v in items if str(v).strip()]
        if not cleaned:
            return ptext(tr("NONE_LISTED"))
        lines = [f"{i + 1}. {escape(val)}" for i, val in enumerate(cleaned)]
        return Paragraph("<br/>".join(lines), style_note)

    def top_actions(findings_list: object) -> list[dict[str, str]]:
        if not isinstance(findings_list, list):
            return []
        actions: list[dict[str, str]] = []
        for finding in findings_list:
            if not isinstance(finding, dict):
                continue
            fid = str(finding.get("finding_id", "")).strip().upper()
            source = human_source(finding.get("suspected_source"))
            confidence = _as_float(finding.get("confidence_0_to_1")) or 0.0
            checks = finding.get("quick_checks")
            action_text = (
                str(checks[0]).strip()
                if isinstance(checks, list) and checks and str(checks[0]).strip()
                else tr("REPEAT_RUN_AFTER_CHECKING_SENSOR_MOUNTING_AND_ROUTING")
            )
            if fid in {"REF_SPEED", "REF_WHEEL", "REF_ENGINE", "REF_SAMPLE_RATE"}:
                priority = tr("HIGH")
                eta = tr("T_10_20_MIN")
            elif confidence >= 0.72:
                priority = tr("HIGH")
                eta = tr("T_20_40_MIN")
            elif confidence >= 0.45:
                priority = tr("MEDIUM")
                eta = tr("T_15_30_MIN")
            else:
                priority = tr("LOW")
                eta = tr("T_10_20_MIN")
            reason = str(finding.get("evidence_summary", "")).strip()
            if len(reason) > 180:
                reason = reason[:177].rstrip() + "..."
            actions.append(
                {
                    "priority": priority,
                    "action": action_text,
                    "why": reason
                    or tr(
                        "SOURCE_EVIDENCE_REQUIRES_ADDITIONAL_CHECKS",
                        source=source,
                    ),
                    "eta": eta,
                }
            )
            if len(actions) >= 3:
                break
        return actions

    def location_hotspots(samples_obj: object) -> tuple[list[dict[str, object]], str, int, int]:
        if not isinstance(samples_obj, list):
            return [], tr("LOCATION_ANALYSIS_UNAVAILABLE"), 0, 0
        all_locations: set[str] = set()
        amp_by_location: dict[str, list[float]] = defaultdict(list)
        for sample in samples_obj:
            if not isinstance(sample, dict):
                continue
            client_name = str(sample.get("client_name") or "").strip()
            client_id = str(sample.get("client_id") or "").strip()
            location = client_name or (
                f"Sensor {client_id[-4:]}" if client_id else tr("UNLABELED_SENSOR")
            )
            all_locations.add(location)
            amp = _as_float(sample.get("dominant_peak_amp_g"))
            if amp is None:
                amp = _as_float(sample.get("accel_magnitude_rms_g"))
            if amp is not None and amp > 0:
                amp_by_location[location].append(amp)

        rows: list[dict[str, object]] = []
        for location, amps in amp_by_location.items():
            rows.append(
                {
                    "location": location,
                    "count": len(amps),
                    "peak_g": max(amps),
                    "mean_g": mean(amps),
                }
            )
        rows.sort(key=lambda row: (float(row["peak_g"]), float(row["mean_g"])), reverse=True)
        if not rows:
            return (
                [],
                tr("NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND"),
                0,
                len(all_locations),
            )

        active_count = len(rows)
        monitored_count = len(all_locations)
        strongest = rows[0]
        strongest_loc = str(strongest["location"])
        strongest_peak = float(strongest["peak_g"])
        summary = tr(
            "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF",
            active_count=active_count,
            monitored_count=monitored_count,
            strongest_loc=strongest_loc,
            strongest_peak=strongest_peak,
        )
        if (
            monitored_count >= 3
            and active_count == monitored_count
            and "wheel" in strongest_loc.lower()
        ):
            if len(rows) >= 2:
                second_peak = float(rows[1]["peak_g"])
                if second_peak > 0 and (strongest_peak / second_peak) >= 1.15:
                    summary += tr(
                        "SINCE_ALL_SENSORS_SAW_THE_SIGNATURE_BUT_STRONGEST",
                        strongest_loc=strongest_loc,
                    )
        return rows, summary, active_count, monitored_count

    def mk_table(
        data: list[list[object]],
        col_widths: list[int] | None = None,
        header: bool = True,
        repeat_rows: int | None = None,
    ) -> Table:
        table = Table(
            data,
            colWidths=col_widths,
            repeatRows=repeat_rows if repeat_rows is not None else (1 if header else 0),
        )
        style = TableStyle(
            [
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, colors.HexColor("#b9c7d5")),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#b9c7d5")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#d6dee8")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
        if header:
            style.add("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5"))
            style.add("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f3a52"))
            style.add("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")
            style.add("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor("#c8d3df"))
        table.setStyle(style)
        return table

    def downsample(
        points: list[tuple[float, float]], max_points: int = 260
    ) -> list[tuple[float, float]]:
        if len(points) <= max_points:
            return points
        step = max(1, len(points) // max_points)
        sampled = [points[i] for i in range(0, len(points), step)]
        if sampled[-1] != points[-1]:
            sampled.append(points[-1])
        return sampled

    def line_plot(
        *,
        title: str,
        x_label: str,
        y_label: str,
        series: list[tuple[str, str, list[tuple[float, float]]]],
    ) -> Drawing:
        drawing = Drawing(content_width, 230)
        plot_x0 = 48
        plot_y0 = 34
        plot_w = content_width - 72
        plot_h = 160

        drawing.add(
            String(
                8,
                202,
                title,
                fontName="Helvetica-Bold",
                fontSize=9,
                fillColor=colors.HexColor("#1f3a52"),
            )
        )
        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0 + plot_w,
                plot_y0,
                strokeColor=colors.HexColor("#7b8da0"),
            )
        )
        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0,
                plot_y0 + plot_h,
                strokeColor=colors.HexColor("#7b8da0"),
            )
        )
        drawing.add(String(plot_x0 + (plot_w / 2) - 10, 10, x_label, fontSize=7))
        drawing.add(String(6, plot_y0 + (plot_h / 2), y_label, fontSize=7))

        active_series = [
            (name, color, downsample(points)) for name, color, points in series if points
        ]
        if not active_series:
            drawing.add(String(150, 110, tr("PLOT_NO_DATA_AVAILABLE"), fontSize=8))
            return drawing

        all_points = [point for _name, _color, points in active_series for point in points]
        x_min = min(point[0] for point in all_points)
        x_max = max(point[0] for point in all_points)
        y_min = min(point[1] for point in all_points)
        y_max = max(point[1] for point in all_points)
        if abs(x_max - x_min) < 1e-9:
            x_max = x_min + 1.0
        if abs(y_max - y_min) < 1e-9:
            y_max = y_min + 1.0

        def map_x(x_val: float) -> float:
            return plot_x0 + ((x_val - x_min) / (x_max - x_min) * plot_w)

        def map_y(y_val: float) -> float:
            return plot_y0 + ((y_val - y_min) / (y_max - y_min) * plot_h)

        legend_x = plot_x0 + 4
        legend_y = 192
        for idx, (name, color, points) in enumerate(active_series):
            flat_points: list[float] = []
            for x_val, y_val in points:
                flat_points.append(map_x(x_val))
                flat_points.append(map_y(y_val))
            drawing.add(
                PolyLine(
                    flat_points,
                    strokeColor=colors.HexColor(color),
                    strokeWidth=1.2,
                )
            )
            drawing.add(
                String(
                    legend_x + (idx * 150),
                    legend_y,
                    name,
                    fontSize=7,
                    fillColor=colors.HexColor(color),
                )
            )

        drawing.add(
            String(
                plot_x0 + plot_w - 120,
                plot_y0 - 12,
                f"x:[{x_min:.2f}, {x_max:.2f}]",
                fontSize=6.5,
                fillColor=colors.HexColor("#5a6778"),
            )
        )
        drawing.add(
            String(
                plot_x0 + plot_w - 120,
                plot_y0 + plot_h + 4,
                f"y:[{y_min:.3f}, {y_max:.3f}]",
                fontSize=6.5,
                fillColor=colors.HexColor("#5a6778"),
            )
        )
        return drawing

    def req(value: object, consequence_key: str) -> str:
        return _required_text(value, tr(consequence_key), lang=lang)

    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    quality = summary.get("data_quality", {})
    required_missing = quality.get("required_missing_pct", {}) if isinstance(quality, dict) else {}
    speed_cov = quality.get("speed_coverage", {}) if isinstance(quality, dict) else {}
    accel_sanity = quality.get("accel_sanity", {}) if isinstance(quality, dict) else {}
    outliers = quality.get("outliers", {}) if isinstance(quality, dict) else {}
    findings = summary.get("findings", [])
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}

    metadata_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("START_TIME_UTC"),
            req(summary.get("start_time_utc"), "CONSEQUENCE_TIMELINE_ALIGNMENT_IMPOSSIBLE"),
        ],
        [
            tr("END_TIME_UTC"),
            req(summary.get("end_time_utc"), "CONSEQUENCE_DURATION_INFERRED_FROM_LAST_SAMPLE"),
        ],
        [
            tr("SENSOR_MODEL"),
            req(summary.get("sensor_model"), "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED"),
        ],
        [
            tr("RAW_SAMPLE_RATE_HZ_LABEL"),
            req(summary.get("raw_sample_rate_hz"), "CONSEQUENCE_FREQUENCY_CONFIDENCE_REDUCED"),
        ],
        [
            tr("FEATURE_INTERVAL_S_LABEL"),
            req(
                summary.get("feature_interval_s"),
                "CONSEQUENCE_TIME_DENSITY_INTERPRETATION_REDUCED",
            ),
        ],
        [
            tr("FFT_WINDOW_SIZE_SAMPLES_LABEL"),
            req(summary.get("fft_window_size_samples"), "CONSEQUENCE_SPECTRAL_RESOLUTION_UNKNOWN"),
        ],
        [
            tr("FFT_WINDOW_TYPE_LABEL"),
            req(summary.get("fft_window_type"), "CONSEQUENCE_WINDOW_LEAKAGE_ASSUMPTIONS_UNKNOWN"),
        ],
        [
            tr("PEAK_PICKER_METHOD_LABEL"),
            req(summary.get("peak_picker_method"), "CONSEQUENCE_PEAK_REPRODUCIBILITY_UNCLEAR"),
        ],
        [
            tr("TIRE_WIDTH_MM_LABEL"),
            req(
                summary.get("metadata", {}).get("tire_width_mm"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("TIRE_ASPECT_PCT_LABEL"),
            req(
                summary.get("metadata", {}).get("tire_aspect_pct"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("RIM_SIZE_IN_LABEL"),
            req(
                summary.get("metadata", {}).get("rim_in"),
                "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("FINAL_DRIVE_RATIO_LABEL"),
            req(
                summary.get("metadata", {}).get("final_drive_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE"),
        ],
        [
            tr("CURRENT_GEAR_RATIO_LABEL"),
            req(
                summary.get("metadata", {}).get("current_gear_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            )
            if isinstance(summary.get("metadata"), dict)
            else req(None, "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE"),
        ],
    ]

    location_rows, location_summary, active_locations, monitored_locations = location_hotspots(
        summary.get("samples", [])
    )
    finding_ids = {
        str(item.get("finding_id", "")).strip().upper()
        for item in findings
        if isinstance(item, dict)
    }
    top_finding = (
        findings[0]
        if isinstance(findings, list) and findings and isinstance(findings[0], dict)
        else {}
    )
    top_source = (
        human_source(top_finding.get("suspected_source"))
        if isinstance(top_finding, dict)
        else tr("UNKNOWN")
    )
    top_confidence = (
        _as_float(top_finding.get("confidence_0_to_1")) if isinstance(top_finding, dict) else 0.0
    )
    if any(fid.startswith("REF_") for fid in finding_ids):
        overall_status = tr("STATUS_REFERENCE_GAPS")
    elif (top_confidence or 0.0) >= 0.7:
        overall_status = tr("STATUS_ACTIONABLE_HIGH_CONFIDENCE")
    else:
        overall_status = tr("STATUS_PRELIMINARY")

    speed_ready = (_as_float(speed_cov.get("non_null_pct")) or 0.0) >= SPEED_COVERAGE_MIN_PCT
    sample_rate_ready = _as_float(summary.get("raw_sample_rate_hz")) is not None
    engine_ready = "REF_ENGINE" not in finding_ids
    readiness_line = tr(
        "READINESS_LINE",
        speed_state=tr("READY") if speed_ready else tr("MISSING_LOW"),
        sample_rate_state=tr("READY") if sample_rate_ready else tr("MISSING_STATE"),
        engine_state=tr("READY") if engine_ready else tr("MISSING_LOW"),
        active=active_locations,
        total=monitored_locations if monitored_locations else 0,
    )

    likely_origin = tr("UNKNOWN")
    origin_reason = tr("ORIGIN_NOT_ENOUGH_LOCATION_CONTRAST")
    if location_rows:
        strongest_location = str(location_rows[0]["location"])
        strongest_peak = float(location_rows[0]["peak_g"])
        second_peak = (
            float(location_rows[1]["peak_g"]) if len(location_rows) > 1 else strongest_peak
        )
        dominance = (strongest_peak / second_peak) if second_peak > 0 else 1.0
        if "wheel" in strongest_location.lower():
            likely_origin = tr("LOCATION_WHEEL_AREA", location=strongest_location)
        else:
            likely_origin = strongest_location
        origin_reason = tr(
            "ORIGIN_STRONGEST_PEAK_DOMINANCE",
            location=strongest_location,
            dominance=dominance,
        )
    elif isinstance(top_finding, dict):
        likely_origin = top_source
        origin_reason = str(top_finding.get("evidence_summary", tr("LOCATION_RANKING_UNAVAILABLE")))

    story: list[object] = [
        Paragraph(tr("NVH_DIAGNOSTIC_REPORT"), style_title),
        mk_table(
            [
                [
                    tr("REPORT_DATE"),
                    tr("RUN_FILE"),
                    tr("RUN_ID"),
                    tr("DURATION"),
                ],
                [
                    str(report_date)[:19].replace("T", " "),
                    str(summary.get("file_name", "")),
                    str(summary.get("run_id", "")),
                    str(
                        summary.get(
                            "record_length",
                            tr("MISSING_DURATION_UNAVAILABLE"),
                        )
                    ),
                ],
            ],
            col_widths=[150, 260, 220, 110],
        ),
        Paragraph(tr("RUN_TRIAGE"), style_h2),
        mk_table(
            [
                [tr("ITEM"), tr("SUMMARY")],
                [tr("OVERALL_STATUS"), Paragraph(overall_status, style_note)],
                [
                    tr("MOST_LIKELY_ORIGIN"),
                    Paragraph(f"{likely_origin}<br/>{escape(origin_reason)}", style_note),
                ],
                [tr("DATA_READINESS"), Paragraph(readiness_line, style_note)],
            ],
            col_widths=[170, 570],
        ),
    ]

    action_rows = [
        [
            tr("PRIORITY"),
            tr("RECOMMENDED_ACTION"),
            tr("WHY"),
            tr("ESTIMATED_TIME"),
        ]
    ]
    for action in top_actions(findings):
        action_rows.append(
            [
                action["priority"],
                Paragraph(action["action"], style_note),
                Paragraph(action["why"], style_note),
                action["eta"],
            ]
        )
    if len(action_rows) == 1:
        action_rows.append(
            [
                tr("INFO"),
                tr("COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
                tr("NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
                tr("T_10_20_MIN"),
            ]
        )
    story.extend(
        [
            Paragraph(tr("TOP_ACTIONS"), style_h2),
            mk_table(action_rows, col_widths=[70, 240, 370, 90]),
        ]
    )

    warnings = summary.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        warning_text = "<br/>".join(str(w) for w in warnings)
        story.extend(
            [
                Spacer(1, 6),
                Paragraph(
                    f"<b>{tr('INPUT_WARNINGS')}</b><br/>{warning_text}",
                    style_note,
                ),
            ]
        )

    story.extend([PageBreak(), Paragraph(tr("RANKED_FINDINGS"), style_h2)])
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings[:5], start=1):
            if not isinstance(finding, dict):
                continue
            amp = finding.get("amplitude_metric", {})
            title = human_finding_title(finding, idx)
            source = human_source(finding.get("suspected_source"))
            confidence_pct = f"{((_as_float(finding.get('confidence_0_to_1')) or 0.0) * 100):.0f}%"
            story.extend(
                [
                    Paragraph(title, style_h3),
                    Paragraph(
                        (
                            f"<b>{tr('LIKELY_SOURCE_LABEL')}:</b> {source} &nbsp;&nbsp; "
                            f"<b>{tr('CONFIDENCE_LABEL')}:</b> {confidence_pct}"
                        ),
                        style_note,
                    ),
                    Paragraph(str(finding.get("evidence_summary", "")), style_note),
                    mk_table(
                        [
                            [tr("MATCHED_FREQUENCY_ORDER"), tr("AMPLITUDE_SUMMARY")],
                            [
                                human_frequency_text(finding.get("frequency_hz_or_order")),
                                human_amp_text(amp),
                            ],
                        ],
                        col_widths=[250, 490],
                    ),
                    Paragraph(f"<b>{tr('QUICK_CHECKS')}</b>", style_note),
                    human_list(finding.get("quick_checks")),
                    Spacer(1, 5),
                ]
            )
    else:
        story.append(
            Paragraph(
                tr("NO_FINDINGS_WERE_GENERATED_FROM_THE_AVAILABLE_DATA"),
                style_body,
            )
        )

    story.extend([Paragraph(tr("WHERE_VIBRATION_IS_STRONGEST"), style_h2)])
    story.append(Paragraph(location_summary, style_body))
    if location_rows:
        strongest_peak = float(location_rows[0]["peak_g"])
        location_table = [
            [
                tr("LOCATION"),
                tr("PEAK_AMPLITUDE_G"),
                tr("MEAN_AMPLITUDE_G"),
                tr("SAMPLES"),
                tr("RELATIVE"),
            ]
        ]
        for row in location_rows[:8]:
            peak = float(row["peak_g"])
            rel = (peak / strongest_peak * 100.0) if strongest_peak > 0 else 0.0
            location_table.append(
                [
                    str(row["location"]),
                    f"{peak:.4f}",
                    f"{float(row['mean_g']):.4f}",
                    str(int(row["count"])),
                    tr("REL_0F_OF_STRONGEST", rel=rel),
                ]
            )
        story.append(mk_table(location_table, col_widths=[220, 140, 140, 90, 120]))

    story.extend([PageBreak(), Paragraph(tr("SPEED_BINNED_ANALYSIS"), style_h2)])
    skipped_reason = summary.get("speed_breakdown_skipped_reason")
    if skipped_reason:
        story.append(Paragraph(str(skipped_reason), style_body))
    else:
        speed_rows = [
            [
                tr("SPEED_RANGE"),
                tr("SAMPLES"),
                tr("MEAN_AMPLITUDE_G"),
                tr("MAX_AMPLITUDE_G"),
            ]
        ]
        for row in summary.get("speed_breakdown", []):
            if not isinstance(row, dict):
                continue
            speed_rows.append(
                [
                    str(row.get("speed_range", "")),
                    str(int(_as_float(row.get("count")) or 0)),
                    req(row.get("mean_amplitude_g"), "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE"),
                    req(row.get("max_amplitude_g"), "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE"),
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
        story.append(mk_table(speed_rows, col_widths=[130, 90, 140, 140]))

    story.extend([Paragraph(tr("PLOTS"), style_h2)])
    accel_mag = plots.get("accel_magnitude", []) if isinstance(plots, dict) else []
    accel_axes = plots.get("accel_axes", {}) if isinstance(plots, dict) else {}
    dominant_freq = plots.get("dominant_freq", []) if isinstance(plots, dict) else []
    amp_vs_speed = plots.get("amp_vs_speed", []) if isinstance(plots, dict) else []

    story.append(
        line_plot(
            title=tr("PLOT_ACCEL_MAG_OVER_TIME"),
            x_label=tr("TIME_S"),
            y_label="|a| (g)",
            series=[(tr("PLOT_SERIES_MAGNITUDE"), "#1f77b4", accel_mag)],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        line_plot(
            title=tr("PLOT_PER_AXIS_ACCEL_OVER_TIME"),
            x_label=tr("TIME_S"),
            y_label="accel (g)",
            series=[
                (
                    "accel_x_g",
                    "#d62728",
                    accel_axes.get("x", []) if isinstance(accel_axes, dict) else [],
                ),
                (
                    "accel_y_g",
                    "#2ca02c",
                    accel_axes.get("y", []) if isinstance(accel_axes, dict) else [],
                ),
                (
                    "accel_z_g",
                    "#1f77b4",
                    accel_axes.get("z", []) if isinstance(accel_axes, dict) else [],
                ),
            ],
        )
    )
    if dominant_freq:
        story.append(Spacer(1, 6))
        story.append(
            line_plot(
                title=tr("PLOT_DOM_FREQ_OVER_TIME"),
                x_label=tr("TIME_S"),
                y_label=tr("FREQUENCY_HZ"),
                series=[("dominant_freq_hz", "#9467bd", dominant_freq)],
            )
        )
    else:
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                tr("PLOT_DOM_FREQ_SKIPPED"),
                style_note,
            )
        )

    if amp_vs_speed:
        story.append(Spacer(1, 6))
        story.append(
            line_plot(
                title=tr("PLOT_AMP_VS_SPEED_BINS"),
                x_label=tr("SPEED_KM_H"),
                y_label=tr("PLOT_Y_MEAN_AMPLITUDE_G"),
                series=[(tr("PLOT_SERIES_MEAN_AMPLITUDE"), "#ff7f0e", amp_vs_speed)],
            )
        )

    story.extend(
        [
            Spacer(1, 8),
            Paragraph(
                (tr("THIS_REPORT_IS_GENERATED_FROM_EXPLICIT_REFERENCES_ONLY")),
                style_note,
            ),
        ]
    )

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_A_DATA_QUALITY_CHECKS"), style_h2)])
    missing_rows = [[tr("REQUIRED_COLUMN"), tr("MISSING")]]
    for col_name in ("t_s", "speed_kmh", "accel_x_g", "accel_y_g", "accel_z_g"):
        pct = _as_float(required_missing.get(col_name))
        missing_text = req(None, "CONSEQUENCE_QUALITY_METRIC_UNAVAILABLE")
        missing_rows.append(
            [
                col_name,
                f"{pct:.1f}%" if pct is not None else missing_text,
            ]
        )
    story.append(mk_table(missing_rows, col_widths=[300, 120]))

    speed_note = tr(
        "SPEED_COVERAGE_LINE",
        non_null_pct=f"{_as_float(speed_cov.get('non_null_pct')) or 0.0:.1f}",
        min_kmh=req(speed_cov.get("min_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE"),
        max_kmh=req(speed_cov.get("max_kmh"), "CONSEQUENCE_SPEED_BINS_UNAVAILABLE"),
    )
    story.append(Paragraph(speed_note, style_body))

    sanity_rows = [
        [tr("AXIS"), tr("MEAN_G"), tr("VARIANCE_G_2")],
        [
            "X",
            req(accel_sanity.get("x_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("x_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
        [
            "Y",
            req(accel_sanity.get("y_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("y_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
        [
            "Z",
            req(accel_sanity.get("z_mean_g"), "CONSEQUENCE_MEAN_UNAVAILABLE"),
            req(accel_sanity.get("z_variance_g2"), "CONSEQUENCE_VARIANCE_UNAVAILABLE"),
        ],
    ]
    story.append(mk_table(sanity_rows, col_widths=[100, 170, 170]))

    limit_text = req(accel_sanity.get("sensor_limit_g"), "CONSEQUENCE_SENSOR_LIMIT_UNKNOWN")
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

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_B_FULL_RUN_METADATA"), style_h2)])
    story.append(mk_table(metadata_rows, col_widths=[250, 470]))

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_C_DETAILED_FINDINGS_TABLE"), style_h2)])
    detailed_rows: list[list[object]] = [
        [
            ptext(tr("FINDING"), header=True),
            ptext(tr("LIKELY_SOURCE"), header=True),
            ptext(tr("WHY_WE_THINK_THIS"), header=True),
            ptext(tr("MATCHED_FREQUENCY_ORDER"), header=True),
            ptext(tr("AMPLITUDE_SUMMARY"), header=True),
            ptext(tr("CONFIDENCE_LABEL"), header=True),
            ptext(tr("QUICK_CHECKS"), header=True),
        ]
    ]
    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings, start=1):
            if not isinstance(finding, dict):
                continue
            detailed_rows.append(
                [
                    ptext(human_finding_title(finding, idx)),
                    ptext(human_source(finding.get("suspected_source"))),
                    ptext(finding.get("evidence_summary", "")),
                    ptext(human_frequency_text(finding.get("frequency_hz_or_order"))),
                    ptext(human_amp_text(finding.get("amplitude_metric"))),
                    ptext(f"{((_as_float(finding.get('confidence_0_to_1')) or 0.0) * 100):.0f}%"),
                    human_list(finding.get("quick_checks")),
                ]
            )
    else:
        detailed_rows.append(
            [
                ptext(tr("NO_DIAGNOSTIC_FINDINGS")),
                ptext(tr("UNKNOWN")),
                ptext(tr("NO_FINDINGS_WERE_GENERATED_FROM_THE_AVAILABLE_DATA")),
                ptext(tr("REFERENCE_NOT_AVAILABLE")),
                ptext(tr("NOT_AVAILABLE")),
                ptext("0%"),
                ptext(tr("RECORD_ADDITIONAL_DATA")),
            ]
        )
    story.append(mk_table(detailed_rows, col_widths=[90, 84, 230, 118, 166, 58, 70], repeat_rows=1))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=24,
        rightMargin=24,
        topMargin=28,
        bottomMargin=22,
    )

    def draw_footer(canvas, document) -> None:  # pragma: no cover - formatting callback
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5a6778"))
        canvas.drawString(document.leftMargin, 12, tr("REPORT_FOOTER_TITLE"))
        canvas.drawRightString(
            page_size[0] - document.rightMargin,
            12,
            tr("PAGE_LABEL", page=canvas.getPageNumber()),
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def build_report_pdf(summary: dict[str, object]) -> bytes:
    try:
        return _reportlab_pdf(summary)
    except Exception:
        return _fallback_pdf(summary)
