from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

UTC = timezone.utc
from io import BytesIO
from statistics import mean

from .report_analysis import (
    _as_float,
    _normalize_lang,
    _required_text,
)
from .report_i18n import tr as _tr
from .report_i18n import variants as _tr_variants
from .report_theme import FINDING_SOURCE_COLORS, REPORT_COLORS, REPORT_PLOT_COLORS

LOGGER = logging.getLogger(__name__)


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

    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        KeepTogether,
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

    def text(en_text: str, nl_text: str) -> str:
        return nl_text if lang == "nl" else en_text

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleMain",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        spaceAfter=8,
    )
    style_h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        spaceAfter=4,
        spaceBefore=8,
    )
    style_body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    style_note = ParagraphStyle(
        "Note",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
    )
    style_table_head = ParagraphStyle(
        "TableHead",
        parent=style_note,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.0,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
    )
    style_h3 = ParagraphStyle(
        "H3",
        parent=styles["Heading3"],
        fontSize=10,
        leading=12,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
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
            "vib_mag_rms_g": text("Vibration magnitude RMS", "Trillingsgrootte RMS"),
            "vib_mag_p2p_g": text(
                "Vibration magnitude peak-to-peak",
                "Trillingsgrootte piek-tot-piek",
            ),
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
                else text(
                    "Perform direct mechanical inspection on the highest-risk component path.",
                    "Voer een directe mechanische inspectie uit op het hoogste-risicopad.",
                )
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

    def location_hotspots(
        samples_obj: object,
        findings_obj: object,
    ) -> tuple[list[dict[str, object]], str, int, int]:
        if not isinstance(samples_obj, list):
            return [], tr("LOCATION_ANALYSIS_UNAVAILABLE"), 0, 0
        all_locations: set[str] = set()
        amp_by_location: dict[str, list[float]] = defaultdict(list)

        matched_points: list[dict[str, object]] = []
        if isinstance(findings_obj, list):
            for finding in findings_obj:
                if not isinstance(finding, dict):
                    continue
                rows = finding.get("matched_points")
                if isinstance(rows, list) and rows:
                    matched_points = [row for row in rows if isinstance(row, dict)]
                    break

        if matched_points:
            for row in matched_points:
                location = str(row.get("location") or "").strip()
                amp = _as_float(row.get("amp"))
                if not location:
                    continue
                all_locations.add(location)
                if amp is not None and amp > 0:
                    amp_by_location[location].append(amp)
        else:
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
                    amp = _as_float(sample.get("vib_mag_rms_g"))
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
        if matched_points:
            summary = text(
                (
                    "Order-matched comparison: strongest response is at {strongest_loc} "
                    "({strongest_peak:.4f} g)."
                ),
                (
                    "Orde-gematchte vergelijking: sterkste respons zit bij {strongest_loc} "
                    "({strongest_peak:.4f} g)."
                ),
            ).format(strongest_loc=strongest_loc, strongest_peak=strongest_peak)
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
                (
                    "LINEABOVE",
                    (0, 0),
                    (-1, 0),
                    0.7,
                    colors.HexColor(REPORT_COLORS["table_header_border"]),
                ),
                (
                    "LINEBELOW",
                    (0, 0),
                    (-1, 0),
                    0.7,
                    colors.HexColor(REPORT_COLORS["table_header_border"]),
                ),
                (
                    "LINEBELOW",
                    (0, 1),
                    (-1, -1),
                    0.35,
                    colors.HexColor(REPORT_COLORS["table_row_border"]),
                ),
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
            style.add(
                "BACKGROUND", (0, 0), (-1, 0), colors.HexColor(REPORT_COLORS["table_header_bg"])
            )
            style.add("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(REPORT_COLORS["text_primary"]))
            style.add("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")
            style.add("BOX", (0, 0), (-1, -1), 0.45, colors.HexColor(REPORT_COLORS["table_box"]))
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
        drawing = Drawing(content_width, 236)
        plot_x0 = 52
        plot_y0 = 34
        plot_w = content_width - 88
        plot_h = 160

        drawing.add(
            String(
                8,
                214,
                title,
                fontName="Helvetica-Bold",
                fontSize=9,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )

        active_series = [
            (name, color, downsample(points)) for name, color, points in series if points
        ]
        if not active_series:
            drawing.add(
                String(
                    8,
                    198,
                    tr("PLOT_NO_DATA_AVAILABLE"),
                    fontSize=8,
                    fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
                )
            )
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
        y_min = min(0.0, y_min)

        def map_x(x_val: float) -> float:
            return plot_x0 + ((x_val - x_min) / (x_max - x_min) * plot_w)

        def map_y(y_val: float) -> float:
            return plot_y0 + ((y_val - y_min) / (y_max - y_min) * plot_h)

        for idx in range(6):
            frac = idx / 5.0
            gx = plot_x0 + (frac * plot_w)
            gy = plot_y0 + (frac * plot_h)
            drawing.add(
                Line(
                    gx,
                    plot_y0,
                    gx,
                    plot_y0 + plot_h,
                    strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                    strokeWidth=0.4,
                )
            )
            drawing.add(
                Line(
                    plot_x0,
                    gy,
                    plot_x0 + plot_w,
                    gy,
                    strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                    strokeWidth=0.4,
                )
            )
            drawing.add(
                String(
                    gx - 10,
                    plot_y0 - 12,
                    f"{(x_min + frac * (x_max - x_min)):.0f}",
                    fontSize=6.5,
                    fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
                )
            )
            drawing.add(
                String(
                    plot_x0 - 30,
                    gy - 2,
                    f"{(y_min + frac * (y_max - y_min)):.1f}",
                    fontSize=6.5,
                    fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
                )
            )

        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0 + plot_w,
                plot_y0,
                strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
            )
        )
        drawing.add(
            Line(
                plot_x0,
                plot_y0,
                plot_x0,
                plot_y0 + plot_h,
                strokeColor=colors.HexColor(REPORT_COLORS["axis"]),
            )
        )
        drawing.add(
            String(
                plot_x0 + (plot_w / 2) - 18,
                10,
                x_label,
                fontSize=7,
                fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
            )
        )
        drawing.add(
            String(
                8,
                plot_y0 + (plot_h / 2),
                y_label,
                fontSize=7,
                fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
            )
        )

        legend_x = plot_x0 + 4
        legend_y = 196
        for idx, (name, color, points) in enumerate(active_series):
            flat_points: list[float] = []
            for x_val, y_val in points:
                flat_points.append(map_x(x_val))
                flat_points.append(map_y(y_val))
            drawing.add(PolyLine(flat_points, strokeColor=colors.HexColor(color), strokeWidth=1.3))
            drawing.add(
                Rect(
                    legend_x + (idx * 150),
                    legend_y - 2,
                    8,
                    8,
                    fillColor=colors.HexColor(color),
                    strokeColor=colors.HexColor(color),
                )
            )
            drawing.add(
                String(
                    legend_x + 11 + (idx * 150),
                    legend_y - 1,
                    name,
                    fontSize=7,
                    fillColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
                )
            )
        return drawing

    def _canonical_location(raw: object) -> str:
        token = str(raw or "").strip().lower().replace("_", "-")
        if "front" in token and "left" in token and "wheel" in token:
            return "front-left wheel"
        if "front" in token and "right" in token and "wheel" in token:
            return "front-right wheel"
        if "rear" in token and "left" in token and "wheel" in token:
            return "rear-left wheel"
        if "rear" in token and "right" in token and "wheel" in token:
            return "rear-right wheel"
        if "trunk" in token:
            return "trunk"
        if "driveshaft" in token or "tunnel" in token:
            return "driveshaft tunnel"
        if "engine" in token:
            return "engine bay"
        if "driver" in token:
            return "driver seat"
        return token

    def _source_color(source: object) -> str:
        src = str(source or "unknown").strip().lower()
        return FINDING_SOURCE_COLORS.get(src, FINDING_SOURCE_COLORS["unknown"])

    def car_location_diagram(top_findings: list[dict[str, object]]) -> Drawing:
        # BMW 640i Gran Coupe reference proportions (official BMW press data):
        # length 5007 mm, width 1894 mm -> L/W ~= 2.64.
        bmw_length_mm = 5007.0
        bmw_width_mm = 1894.0
        length_width_ratio = bmw_length_mm / bmw_width_mm

        drawing_h = 500
        drawing = Drawing(content_width, drawing_h)
        car_h = 370.0
        car_w = car_h / length_width_ratio
        x0 = (content_width - car_w) / 2.0
        y0 = 74.0
        cx = x0 + (car_w / 2)
        cy = y0 + (car_h / 2)

        def _hex_to_rgb(value: str) -> tuple[int, int, int]:
            text_value = value.strip().lstrip("#")
            return (
                int(text_value[0:2], 16),
                int(text_value[2:4], 16),
                int(text_value[4:6], 16),
            )

        def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
            return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

        def _blend(a: str, b: str, t: float) -> str:
            t_clamped = max(0.0, min(1.0, t))
            ar, ag, ab = _hex_to_rgb(a)
            br, bg, bb = _hex_to_rgb(b)
            return _rgb_to_hex(
                (
                    int(round(ar + ((br - ar) * t_clamped))),
                    int(round(ag + ((bg - ag) * t_clamped))),
                    int(round(ab + ((bb - ab) * t_clamped))),
                )
            )

        def _amp_heat_color(norm: float) -> str:
            # Green (less vibration) -> yellow -> red (most vibration).
            if norm <= 0.5:
                return _blend("#2ca25f", "#f0cf4a", norm * 2.0)
            return _blend("#f0cf4a", "#d73027", (norm - 0.5) * 2.0)

        # Outer body
        drawing.add(
            Rect(
                x0,
                y0,
                car_w,
                car_h,
                rx=30,
                ry=30,
                fillColor=colors.HexColor(REPORT_COLORS["surface"]),
                strokeColor=colors.HexColor(REPORT_COLORS["border"]),
                strokeWidth=1.4,
            )
        )
        # Cabin
        drawing.add(
            Rect(
                x0 + (car_w * 0.08),
                y0 + (car_h * 0.10),
                car_w * 0.84,
                car_h * 0.80,
                rx=20,
                ry=20,
                fillColor=colors.HexColor("#ffffff"),
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.7,
            )
        )
        # Center tunnel line
        drawing.add(
            Line(
                cx,
                y0 + 22,
                cx,
                y0 + car_h - 22,
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.8,
            )
        )
        # Axle guides
        front_axle_y = y0 + (car_h * 0.84)
        rear_axle_y = y0 + (car_h * 0.16)
        drawing.add(
            Line(
                x0 + (car_w * 0.14),
                front_axle_y,
                x0 + (car_w * 0.86),
                front_axle_y,
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.6,
            )
        )
        drawing.add(
            Line(
                x0 + (car_w * 0.14),
                rear_axle_y,
                x0 + (car_w * 0.86),
                rear_axle_y,
                strokeColor=colors.HexColor(REPORT_COLORS["table_row_border"]),
                strokeWidth=0.6,
            )
        )
        # Wheels
        wheel_fill = colors.HexColor("#f8fbff")
        wheel_stroke = colors.HexColor(REPORT_COLORS["axis"])
        wheel_x_left = x0 + (car_w * 0.14)
        wheel_x_right = x0 + (car_w * 0.86)
        for wx, wy in [
            (wheel_x_left, front_axle_y),  # front-left
            (wheel_x_right, front_axle_y),  # front-right
            (wheel_x_left, rear_axle_y),  # rear-left
            (wheel_x_right, rear_axle_y),  # rear-right
        ]:
            drawing.add(
                Circle(wx, wy, 14, fillColor=wheel_fill, strokeColor=wheel_stroke, strokeWidth=1.0)
            )

        # Orientation labels
        drawing.add(
            String(
                cx - 20,
                y0 + car_h + 26,
                text("FRONT", "VOOR"),
                fontName="Helvetica-Bold",
                fontSize=10,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )
        drawing.add(
            String(
                cx - 18,
                y0 - 22,
                text("REAR", "ACHTER"),
                fontName="Helvetica-Bold",
                fontSize=10,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )
        drawing.add(
            String(
                x0 - 46,
                cy - 4,
                text("LEFT", "LINKS"),
                fontName="Helvetica-Bold",
                fontSize=10,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )
        drawing.add(
            String(
                x0 + car_w + 16,
                cy - 4,
                text("RIGHT", "RECHTS"),
                fontName="Helvetica-Bold",
                fontSize=10,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )

        # Vehicle coordinates (front = high y, rear = low y; left/right from driver's perspective)
        location_points = {
            "front-left wheel": (wheel_x_left, front_axle_y),
            "front-right wheel": (wheel_x_right, front_axle_y),
            "rear-left wheel": (wheel_x_left, rear_axle_y),
            "rear-right wheel": (wheel_x_right, rear_axle_y),
            "engine bay": (cx, y0 + (car_h * 0.68)),
            "driveshaft tunnel": (cx, cy),
            "driver seat": (x0 + (car_w * 0.36), y0 + (car_h * 0.58)),
            "trunk": (cx, y0 + (car_h * 0.28)),
        }

        active_locations = {
            _canonical_location(loc)
            for loc in summary.get("sensor_locations", [])
            if str(loc).strip()
        }
        amp_by_location: dict[str, float] = {}
        sensor_intensity_rows = summary.get("sensor_intensity_by_location", [])
        if isinstance(sensor_intensity_rows, list):
            for row in sensor_intensity_rows:
                if not isinstance(row, dict):
                    continue
                loc = _canonical_location(row.get("location"))
                p95_g = _as_float(row.get("p95_intensity_g")) or _as_float(row.get("mean_intensity_g"))
                if loc and p95_g is not None and p95_g > 0:
                    amp_by_location[loc] = p95_g
        if not amp_by_location:
            # Backward-compatible fallback for older summaries.
            for row in location_rows:
                if not isinstance(row, dict):
                    continue
                loc = _canonical_location(row.get("location"))
                mean_g = _as_float(row.get("mean_g"))
                if loc and mean_g is not None and mean_g > 0:
                    amp_by_location[loc] = mean_g
        min_amp = min(amp_by_location.values()) if amp_by_location else None
        max_amp = max(amp_by_location.values()) if amp_by_location else None

        highlight: dict[str, str] = {}
        for finding in top_findings[:3]:
            if not isinstance(finding, dict):
                continue
            loc = _canonical_location(finding.get("strongest_location"))
            if loc:
                highlight[loc] = _source_color(
                    finding.get("source") or finding.get("suspected_source")
                )

        drawing.add(
            String(
                8,
                drawing_h - 18,
                tr("SENSOR_PLACEMENT_AND_HOTSPOTS"),
                fontName="Helvetica-Bold",
                fontSize=10,
                fillColor=colors.HexColor(REPORT_COLORS["text_primary"]),
            )
        )
        drawing.add(
            String(
                8,
                drawing_h - 32,
                text(
                    "BMW 640i ratio used: length/width = 5007/1894 (2.64).",
                    "BMW 640i-verhouding gebruikt: lengte/breedte = 5007/1894 (2,64).",
                ),
                fontName="Helvetica",
                fontSize=7.4,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                8,
                drawing_h - 44,
                text(
                    "Heat colors use p95 vibration intensity per location.",
                    "Heat-kleuren gebruiken p95 trillingsintensiteit per locatie.",
                ),
                fontName="Helvetica",
                fontSize=7.2,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )

        for name, (px, py) in location_points.items():
            is_active = name in active_locations or name in amp_by_location
            amp = amp_by_location.get(name)
            if amp is not None and min_amp is not None and max_amp is not None:
                if max_amp > min_amp:
                    norm = (amp - min_amp) / (max_amp - min_amp)
                else:
                    norm = 1.0
                fill = _amp_heat_color(norm)
                radius = 5.0 + (norm * 2.2)
            elif is_active:
                fill = REPORT_COLORS["text_secondary"]
                radius = 5.4
            else:
                fill = "#d3dbe8"
                radius = 4.6

            drawing.add(
                Circle(
                    px,
                    py,
                    radius,
                    fillColor=colors.HexColor(fill),
                    strokeColor=colors.HexColor(highlight.get(name, REPORT_COLORS["ink"])),
                    strokeWidth=1.1 if name in highlight else 0.6,
                )
            )
            drawing.add(
                String(
                    px + 10,
                    py - 2,
                    name,
                    fontSize=6.8,
                    fillColor=colors.HexColor(
                        REPORT_COLORS["ink"] if is_active else REPORT_COLORS["text_muted"]
                    ),
                )
            )

        # Heat legend (green -> red).
        legend_y = 24
        legend_x = 10
        for i in range(0, 11):
            step = i / 10.0
            drawing.add(
                Rect(
                    legend_x + (i * 9),
                    legend_y,
                    9,
                    8,
                    fillColor=colors.HexColor(_amp_heat_color(step)),
                    strokeColor=colors.HexColor(_amp_heat_color(step)),
                    strokeWidth=0.2,
                )
            )
        drawing.add(
            String(
                legend_x,
                legend_y - 10,
                text("Less vibration", "Minder trilling"),
                fontName="Helvetica",
                fontSize=7.2,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
            )
        )
        drawing.add(
            String(
                legend_x + 92,
                legend_y - 10,
                text("Most vibration", "Meeste trilling"),
                fontName="Helvetica",
                fontSize=7.2,
                fillColor=colors.HexColor(REPORT_COLORS["text_muted"]),
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
            text("Acceleration Scale (g/LSB)", "Versnellingsschaal (g/LSB)"),
            req(
                summary.get("accel_scale_g_per_lsb"),
                "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED",
            ),
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
    _ = metadata_rows

    location_rows, location_summary, active_locations, monitored_locations = location_hotspots(
        summary.get("samples", []),
        findings,
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

    origin_reason = tr("ORIGIN_NOT_ENOUGH_LOCATION_CONTRAST")
    if location_rows:
        strongest_location = str(location_rows[0]["location"])
        strongest_peak = float(location_rows[0]["peak_g"])
        second_peak = (
            float(location_rows[1]["peak_g"]) if len(location_rows) > 1 else strongest_peak
        )
        dominance = (strongest_peak / second_peak) if second_peak > 0 else 1.0
        origin_reason = tr(
            "ORIGIN_STRONGEST_PEAK_DOMINANCE",
            location=strongest_location,
            dominance=dominance,
        )
    elif isinstance(top_finding, dict):
        origin_reason = str(top_finding.get("evidence_summary", tr("LOCATION_RANKING_UNAVAILABLE")))

    top_causes = [item for item in summary.get("top_causes", []) if isinstance(item, dict)]
    test_plan = [item for item in summary.get("test_plan", []) if isinstance(item, dict)]
    most_origin = (
        summary.get("most_likely_origin", {})
        if isinstance(summary.get("most_likely_origin"), dict)
        else {}
    )
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )
    run_suitability = [
        item for item in summary.get("run_suitability", []) if isinstance(item, dict)
    ]

    run_header = mk_table(
        [
            [
                Paragraph("<b>VibeSensor</b>", style_h2),
                Paragraph(
                    f"<b>{tr('REPORT_DATE')}:</b> {str(report_date)[:19].replace('T', ' ')}<br/><b>{tr('RUN_ID')}:</b> {summary.get('run_id', '')}",
                    style_note,
                ),
            ],
        ],
        col_widths=[content_width * 0.62, content_width * 0.38],
        header=False,
    )
    run_header.setStyle(
        TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(REPORT_COLORS["surface"]))])
    )

    top_conf_pct = (_as_float(top_finding.get("confidence_0_to_1")) or 0.0) * 100.0
    card_status = mk_table(
        [
            [Paragraph(f"<b>{tr('OVERALL_STATUS')}</b>", style_note)],
            [Paragraph(overall_status, style_note)],
            [
                Paragraph(
                    text(
                        "Use the prioritized concrete checks below to isolate the physical cause.",
                        "Gebruik de geprioriteerde concrete checks hieronder om de fysieke oorzaak te isoleren.",
                    ),
                    style_note,
                )
            ],
        ],
        header=False,
    )
    card_cause = mk_table(
        [
            [
                Paragraph(
                    f"<b>{text('Top suspected cause', 'Top vermoedelijke oorzaak')}</b>", style_note
                )
            ],
            [Paragraph(top_source, style_note)],
            [
                Paragraph(
                    f"{top_conf_pct:.0f}% | {top_finding.get('frequency_hz_or_order', tr('UNKNOWN'))}",
                    style_note,
                )
            ],
        ],
        header=False,
    )
    card_conditions = mk_table(
        [
            [Paragraph(f"<b>{text('Run conditions', 'Runcondities')}</b>", style_note)],
            [
                Paragraph(
                    (
                        f"{tr('DURATION')}: {summary.get('record_length', tr('MISSING_DURATION_UNAVAILABLE'))}<br/>"
                        f"{text('Speed range', 'Snelheidsbereik')}: {(_as_float(speed_stats.get('min_kmh')) or 0.0):.1f}-"
                        f"{(_as_float(speed_stats.get('max_kmh')) or 0.0):.1f} km/h<br/>"
                        f"{text('Speed stddev', 'Snelheid stddev')}: {(_as_float(speed_stats.get('stddev_kmh')) or 0.0):.2f} km/h<br/>"
                        f"{text('Sample rate', 'Bemonsteringsfrequentie')}: {(_as_float(summary.get('raw_sample_rate_hz')) or 0.0):.1f} Hz<br/>"
                        f"{text('Sensors used', 'Gebruikte sensoren')}: {int(_as_float(summary.get('sensor_count_used')) or 0)}"
                    ),
                    style_note,
                )
            ],
        ],
        header=False,
    )
    cards_row = Table(
        [[card_status, card_cause, card_conditions]], colWidths=[content_width / 3.0] * 3
    )
    cards_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    cause_rows = [
        [
            tr("FINDING"),
            tr("LIKELY_SOURCE"),
            tr("CONFIDENCE_LABEL"),
            text("Strongest location", "Sterkste locatie"),
            text("Strongest speed band", "Sterkste snelheidsband"),
        ]
    ]
    for idx, cause in enumerate(top_causes[:3], start=1):
        dominance = _as_float(cause.get("dominance_ratio"))
        loc = str(cause.get("strongest_location") or tr("UNKNOWN"))
        if dominance is not None:
            loc = f"{loc} ({dominance:.2f}x)"
            if bool(cause.get("weak_spatial_separation")):
                loc += f" - {text('weak spatial separation', 'zwakke ruimtelijke scheiding')}"
        cause_rows.append(
            [
                str(idx),
                human_source(cause.get("source") or cause.get("suspected_source")),
                f"{((_as_float(cause.get('confidence')) or _as_float(cause.get('confidence_0_to_1')) or 0.0) * 100):.0f}%",
                loc,
                str(cause.get("strongest_speed_band") or tr("UNKNOWN")),
            ]
        )
    if len(cause_rows) == 1:
        cause_rows.append(["-", tr("UNKNOWN"), "0%", tr("UNKNOWN"), tr("UNKNOWN")])

    if not test_plan:
        test_plan = [
            {
                "what": tr("COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
                "why": tr("NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
                "eta": tr("T_10_20_MIN"),
            }
        ]
    test_plan_rows = [
        [
            text("Step", "Stap"),
            text("What to do", "Wat te doen"),
            text("Why", "Waarom"),
            tr("ESTIMATED_TIME"),
        ]
    ]
    for idx, step in enumerate(test_plan[:5], start=1):
        test_plan_rows.append(
            [
                str(idx),
                Paragraph(str(step.get("what") or ""), style_note),
                Paragraph(str(step.get("why") or ""), style_note),
                str(step.get("eta") or ""),
            ]
        )

    story: list[object] = [
        Paragraph(tr("NVH_DIAGNOSTIC_REPORT"), style_title),
        run_header,
        Spacer(1, 6),
        cards_row,
        Paragraph(tr("RANKED_FINDINGS"), style_h2),
        mk_table(cause_rows, col_widths=[50, 130, 90, 260, 150]),
        Paragraph(text("Next steps test plan", "Volgende stappen testplan"), style_h2),
        mk_table(test_plan_rows, col_widths=[52, 248, 362, 82]),
    ]

    if most_origin:
        story.extend(
            [
                Paragraph(tr("MOST_LIKELY_ORIGIN"), style_h2),
                Paragraph(str(most_origin.get("explanation") or origin_reason), style_note),
            ]
        )

    warnings = summary.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                f"<b>{tr('INPUT_WARNINGS')}</b><br/>{'<br/>'.join(str(w) for w in warnings)}",
                style_note,
            )
        )

    story.extend([PageBreak(), car_location_diagram(top_causes or findings)])
    sensor_stats_rows = [
        row for row in summary.get("sensor_intensity_by_location", []) if isinstance(row, dict)
    ]
    story.extend([PageBreak(), Paragraph(text("Sensor statistics", "Sensorstatistieken"), style_h2)])
    if sensor_stats_rows:
        stat_table_rows = [
            [
                text("Location", "Locatie"),
                text("Samples", "Samples"),
                "P50 (g)",
                "P95 (g)",
                text("Max (g)", "Max (g)"),
                text("Dropped Δ", "Verlies Δ"),
                text("Overflow Δ", "Overflow Δ"),
                text("L1-L5 (%)", "L1-L5 (%)"),
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
                    f"{(_as_float(row.get('p50_intensity_g')) or 0.0):.4f}",
                    f"{(_as_float(row.get('p95_intensity_g')) or 0.0):.4f}",
                    f"{(_as_float(row.get('max_intensity_g')) or 0.0):.4f}",
                    str(int(_as_float(row.get("dropped_frames_delta")) or 0)),
                    str(int(_as_float(row.get("queue_overflow_drops_delta")) or 0)),
                    bucket_pct,
                ]
            )
        story.append(
            mk_table(
                stat_table_rows,
                col_widths=[130, 56, 70, 70, 70, 70, 70, 78],
                repeat_rows=1,
            )
        )
        story.append(
            Paragraph(
                text(
                    "L1-L5 shows approximate time share per severity strength bucket.",
                    "L1-L5 toont de benaderde tijdsverdeling per ernstniveau.",
                ),
                style_note,
            )
        )
    else:
        story.append(Paragraph(tr("NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND"), style_note))

    if isinstance(findings, list) and findings:
        for idx, finding in enumerate(findings[:3], start=1):
            if not isinstance(finding, dict):
                continue
            evidence_metrics = (
                finding.get("evidence_metrics", {})
                if isinstance(finding.get("evidence_metrics"), dict)
                else {}
            )
            confidence_pct = f"{((_as_float(finding.get('confidence_0_to_1')) or 0.0) * 100):.0f}%"
            source = human_source(finding.get("suspected_source"))
            story.extend(
                [
                    PageBreak(),
                    Paragraph(f"{tr('FINDING')} {idx}: {source} ({confidence_pct})", style_h2),
                    Paragraph(text("What we think it is", "Wat we denken dat het is"), style_h3),
                    Paragraph(str(finding.get("evidence_summary", "")), style_note),
                    mk_table(
                        [
                            [text("Metric", "Metriek"), text("Value", "Waarde")],
                            [
                                text("Match rate", "Trefferratio"),
                                f"{((_as_float(evidence_metrics.get('match_rate')) or 0.0) * 100):.1f}%",
                            ],
                            [
                                text("Mean relative error", "Gemiddelde relatieve fout"),
                                f"{(_as_float(evidence_metrics.get('mean_relative_error')) or 0.0):.3f}",
                            ],
                            [
                                text("Mean matched amplitude", "Gemiddelde gematchte amplitude"),
                                f"{(_as_float(evidence_metrics.get('mean_matched_amplitude')) or 0.0):.4f} g",
                            ],
                            [
                                text("Strongest speed band", "Sterkste snelheidsband"),
                                str(finding.get("strongest_speed_band") or tr("UNKNOWN")),
                            ],
                            [
                                text("Strongest location", "Sterkste locatie"),
                                f"{finding.get('strongest_location') or tr('UNKNOWN')} ({(_as_float(finding.get('dominance_ratio')) or 0.0):.2f}x)",
                            ],
                        ],
                        col_widths=[230, 550],
                    ),
                ]
            )
            matched_points = [
                row for row in finding.get("matched_points", []) if isinstance(row, dict)
            ]
            amp_points = []
            freq_measured = []
            freq_pred = []
            for row in matched_points:
                spd = _as_float(row.get("speed_kmh"))
                amp = _as_float(row.get("amp"))
                mhz = _as_float(row.get("matched_hz"))
                phz = _as_float(row.get("predicted_hz"))
                if spd is not None and amp is not None:
                    amp_points.append((spd, amp))
                if spd is not None and mhz is not None:
                    freq_measured.append((spd, mhz))
                if spd is not None and phz is not None:
                    freq_pred.append((spd, phz))
            if amp_points:
                story.append(
                    line_plot(
                        title=text(
                            "Order track: matched amplitude vs speed",
                            "Ordertrack: gematchte amplitude vs snelheid",
                        ),
                        x_label=tr("SPEED_KM_H"),
                        y_label=text("amplitude (g)", "amplitude (g)"),
                        series=[
                            (
                                str(finding.get("frequency_hz_or_order") or tr("UNKNOWN")),
                                _source_color(finding.get("suspected_source")),
                                amp_points,
                            )
                        ],
                    )
                )
            if freq_measured:
                story.append(
                    line_plot(
                        title=text(
                            "Frequency vs speed with predicted order curve",
                            "Frequentie vs snelheid met voorspelde ordecurve",
                        ),
                        x_label=tr("SPEED_KM_H"),
                        y_label=tr("FREQUENCY_HZ"),
                        series=[
                            (
                                text("matched", "gematcht"),
                                REPORT_PLOT_COLORS["vibration"],
                                freq_measured,
                            ),
                            (
                                text("predicted", "voorspeld"),
                                REPORT_PLOT_COLORS["predicted_curve"],
                                freq_pred,
                            ),
                        ],
                    )
                )
            story.extend(
                [
                    Paragraph(text("What to do next", "Volgende stap"), style_h3),
                    Paragraph(
                        str(
                            finding.get("next_sensor_move")
                            or text(
                                "Start with direct inspection at the strongest location and related components.",
                                "Start met directe inspectie op de sterkste locatie en gerelateerde componenten.",
                            )
                        ),
                        style_note,
                    ),
                ]
            )

    story.extend([PageBreak(), Paragraph(tr("SPEED_BINNED_ANALYSIS"), style_h2)])
    steady_speed = bool(speed_stats.get("steady_speed"))
    if steady_speed:
        dist = (
            plots.get("steady_speed_distribution", {})
            if isinstance(plots.get("steady_speed_distribution"), dict)
            else {}
        )
        story.extend(
            [
                Paragraph(
                    text("Amplitude at steady speed", "Amplitude bij constante snelheid"), style_h3
                ),
                mk_table(
                    [
                        [text("Percentile", "Percentiel"), text("Amplitude (g)", "Amplitude (g)")],
                        ["P10", f"{(_as_float(dist.get('p10')) or 0.0):.4f}"],
                        ["P50", f"{(_as_float(dist.get('p50')) or 0.0):.4f}"],
                        ["P90", f"{(_as_float(dist.get('p90')) or 0.0):.4f}"],
                        ["P95", f"{(_as_float(dist.get('p95')) or 0.0):.4f}"],
                    ],
                    col_widths=[140, 160],
                ),
                Paragraph(
                    text(
                        "Speed variation is too small to validate tracking across speed; repeat with a 20-30 km/h sweep.",
                        "Snelheidsvariatie is te klein om tracking over snelheid te valideren; herhaal met een sweep van 20-30 km/u.",
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
                        req(
                            row.get("mean_amplitude_g"),
                            "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE",
                        ),
                        req(
                            row.get("max_amplitude_g"),
                            "CONSEQUENCE_SPEED_BIN_AMPLITUDE_UNAVAILABLE",
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
            story.append(mk_table(speed_rows, col_widths=[130, 90, 140, 140]))

    story.extend([PageBreak(), Paragraph(tr("APPENDIX_A_DATA_QUALITY_CHECKS"), style_h2)])
    if run_suitability:
        suit_rows = [
            [text("Check", "Controle"), text("State", "Status"), text("Explanation", "Toelichting")]
        ]
        for item in run_suitability:
            state = str(item.get("state") or "warn")
            suit_rows.append(
                [str(item.get("check") or ""), state, str(item.get("explanation") or "")]
            )
        story.extend(
            [
                Paragraph(text("Run suitability", "Geschiktheid van de run"), style_h3),
                mk_table(suit_rows, col_widths=[190, 100, 470]),
            ]
        )
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
    metadata_obj = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    timing_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("START_TIME_UTC"),
            req(summary.get("start_time_utc"), "CONSEQUENCE_TIMELINE_ALIGNMENT_IMPOSSIBLE"),
        ],
        [
            tr("END_TIME_UTC"),
            req(summary.get("end_time_utc"), "CONSEQUENCE_DURATION_INFERRED_FROM_LAST_SAMPLE"),
        ],
        [tr("DURATION"), str(summary.get("record_length", tr("MISSING_DURATION_UNAVAILABLE")))],
    ]
    sensor_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("SENSOR_MODEL"),
            req(summary.get("sensor_model"), "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED"),
        ],
        [
            tr("RAW_SAMPLE_RATE_HZ_LABEL"),
            req(summary.get("raw_sample_rate_hz"), "CONSEQUENCE_FREQUENCY_CONFIDENCE_REDUCED"),
        ],
        [
            text("Acceleration Scale (g/LSB)", "Versnellingsschaal (g/LSB)"),
            req(
                summary.get("accel_scale_g_per_lsb"),
                "CONSEQUENCE_SENSOR_SANITY_LIMITS_CANNOT_BE_APPLIED",
            ),
        ],
        [
            text("Sensors used", "Gebruikte sensoren"),
            str(int(_as_float(summary.get("sensor_count_used")) or 0)),
        ],
    ]
    fft_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("FEATURE_INTERVAL_S_LABEL"),
            req(
                summary.get("feature_interval_s"), "CONSEQUENCE_TIME_DENSITY_INTERPRETATION_REDUCED"
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
    ]
    vehicle_rows = [
        [tr("FIELD"), tr("VALUE")],
        [
            tr("TIRE_WIDTH_MM_LABEL"),
            req(metadata_obj.get("tire_width_mm"), "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("TIRE_ASPECT_PCT_LABEL"),
            req(metadata_obj.get("tire_aspect_pct"), "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("RIM_SIZE_IN_LABEL"),
            req(metadata_obj.get("rim_in"), "CONSEQUENCE_WHEEL_REFERENCE_LESS_PRECISE"),
        ],
        [
            tr("FINAL_DRIVE_RATIO_LABEL"),
            req(
                metadata_obj.get("final_drive_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            ),
        ],
        [
            tr("CURRENT_GEAR_RATIO_LABEL"),
            req(
                metadata_obj.get("current_gear_ratio"),
                "CONSEQUENCE_ENGINE_REFERENCE_MAY_BE_UNAVAILABLE",
            ),
        ],
    ]
    story.extend(
        [
            KeepTogether(
                [
                    Paragraph(text("Timing", "Timing"), style_h3),
                    mk_table(timing_rows, col_widths=[250, 470]),
                ]
            ),
            Spacer(1, 4),
            KeepTogether(
                [
                    Paragraph(text("Sensor", "Sensor"), style_h3),
                    mk_table(sensor_rows, col_widths=[250, 470]),
                ]
            ),
            Spacer(1, 4),
            KeepTogether(
                [Paragraph(text("FFT", "FFT"), style_h3), mk_table(fft_rows, col_widths=[250, 470])]
            ),
            Spacer(1, 4),
            KeepTogether(
                [
                    Paragraph(text("Vehicle", "Voertuig"), style_h3),
                    mk_table(vehicle_rows, col_widths=[250, 470]),
                ]
            ),
        ]
    )

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
        pageCompression=0,
    )

    def draw_footer(canvas, document) -> None:  # pragma: no cover - formatting callback
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor(REPORT_COLORS["text_muted"]))
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
        LOGGER.warning(
            "ReportLab PDF generation failed, using fallback PDF renderer.",
            exc_info=True,
        )
        return _fallback_pdf(summary)
