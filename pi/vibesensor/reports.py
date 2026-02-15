from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import BytesIO
from math import pi
from pathlib import Path
from statistics import mean, median

SPEED_BIN_WIDTH_KMH = 5
ASSUMED_TIRE_DIAMETER_IN = 27.7
ORDER_TOLERANCE = 0.22


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:  # NaN check
        return default
    return out


def _wheel_hz(speed_mps: float) -> float:
    if speed_mps <= 0:
        return 0.0
    tire_diameter_m = ASSUMED_TIRE_DIAMETER_IN * 0.0254
    return speed_mps / (pi * tire_diameter_m)


def _infer_order(freq_hz: float, speed_mps: float) -> str:
    base = _wheel_hz(speed_mps)
    if base <= 0:
        if 8.0 <= freq_hz <= 18.0:
            return "1st"
        if 18.0 < freq_hz <= 35.0:
            return "2nd"
        if 35.0 < freq_hz <= 55.0:
            return "3rd"
        return "Other"
    ratio = freq_hz / base
    if abs(ratio - 1.0) <= ORDER_TOLERANCE:
        return "1st"
    if abs(ratio - 2.0) <= ORDER_TOLERANCE:
        return "2nd"
    if abs(ratio - 3.0) <= ORDER_TOLERANCE:
        return "3rd"
    return "Other"


def _speed_bin(speed_mps: float) -> str | None:
    kmh = speed_mps * 3.6
    if kmh <= 0:
        return None
    low = int(kmh // SPEED_BIN_WIDTH_KMH) * SPEED_BIN_WIDTH_KMH
    high = low + SPEED_BIN_WIDTH_KMH - 1
    return f"{low}-{high} km/h"


def _speed_bin_sort_key(label: str) -> int:
    prefix = label.split(" ", 1)[0]
    low_text = prefix.split("-", 1)[0]
    try:
        return int(low_text)
    except ValueError:
        return 0


def _format_duration(seconds: float) -> str:
    total = max(0.0, seconds)
    minutes = int(total // 60)
    rem = total - (minutes * 60)
    return f"{minutes:02d}:{rem:04.1f}"


def _classify_frequency(freq_hz: float) -> tuple[str, str]:
    if 8.0 <= freq_hz <= 18.0:
        return (
            "Wheel/Tire Speed Related Vibration",
            "First repair target is tire and wheel uniformity or wheel balance on all corners.",
        )
    if 18.0 < freq_hz <= 35.0:
        return (
            "Driveline Speed Related Vibration",
            "Check driveshaft balance, joint condition, and driveline alignment angles.",
        )
    if 3.0 <= freq_hz < 8.0:
        return (
            "Road/Suspension Related Vibration",
            "Inspect suspension bushings, mounts, and body resonance paths.",
        )
    if freq_hz > 35.0:
        return (
            "Engine/Accessory Related Vibration",
            "Inspect engine mounts, combustion smoothness, and front-end accessories.",
        )
    return (
        "Other Vibration",
        "Unclassified; inspect mountings, loose hardware, and sensor placement.",
    )


def summarize_log(csv_path: Path) -> dict[str, object]:
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    clients: set[str] = set()
    rows = 0
    peak_hz: list[float] = []
    peak_amp: list[float] = []
    p2p_vals: list[float] = []
    speed_kmh_vals: list[float] = []
    ts_values: list[datetime] = []
    dropped_total_max = 0
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    by_cause: dict[str, int] = {}
    insight_text: dict[str, str] = {}
    totals_map: dict[tuple[str, str], dict[str, float]] = {}
    speed_bin_totals: dict[str, int] = {}
    breakdown_map: dict[tuple[str, str], dict[str, dict[str, float]]] = {}

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            clients.add(str(row.get("client_id", "")).strip())
            ts = _parse_ts(str(row.get("timestamp_iso", "")).strip())
            if ts is not None:
                ts_values.append(ts)
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            speed_mps = _as_float(row.get("speed_mps", 0), 0.0)
            if speed_mps > 0:
                speed_kmh_vals.append(speed_mps * 3.6)
                speed_label = _speed_bin(speed_mps)
                if speed_label:
                    speed_bin_totals[speed_label] = speed_bin_totals.get(speed_label, 0) + 1
            else:
                speed_label = None

            hz = _as_float(row.get("peak1_hz", 0), 0.0)
            amp = _as_float(row.get("peak1_amp", 0), 0.0)
            if hz > 0:
                peak_hz.append(hz)
                cause, detail = _classify_frequency(hz)
                by_cause[cause] = by_cause.get(cause, 0) + 1
                insight_text[cause] = detail
                if amp > 0:
                    peak_amp.append(amp)
                order = _infer_order(hz, speed_mps)
                total_key = (cause, order)
                total_stats = totals_map.setdefault(total_key, {"count": 0.0, "amp_sum": 0.0})
                total_stats["count"] += 1.0
                total_stats["amp_sum"] += max(0.0, amp)
                if speed_label:
                    group = breakdown_map.setdefault(total_key, {})
                    bucket = group.setdefault(speed_label, {"count": 0.0, "amp_sum": 0.0})
                    bucket["count"] += 1.0
                    bucket["amp_sum"] += max(0.0, amp)

            p2p = _as_float(row.get("p2p", 0), 0.0)
            if p2p > 0:
                p2p_vals.append(p2p)
            dropped_total = int(_as_float(row.get("frames_dropped_total", 0), 0.0))
            dropped_total_max = max(dropped_total_max, dropped_total)

    duration_s = 0.0
    if first_ts is not None and last_ts is not None:
        duration_s = max(0.0, (last_ts - first_ts).total_seconds())
    unique_ts = sorted(set(ts_values))
    sample_interval_s = 0.5
    if len(unique_ts) >= 2:
        deltas = [
            (unique_ts[i] - unique_ts[i - 1]).total_seconds()
            for i in range(1, len(unique_ts))
            if (unique_ts[i] - unique_ts[i - 1]).total_seconds() > 0
        ]
        if deltas:
            sample_interval_s = float(median(deltas))
        elif duration_s > 0:
            sample_interval_s = duration_s / max(1, len(unique_ts) - 1)

    top_causes = sorted(by_cause.items(), key=lambda kv: kv[1], reverse=True)
    cause_insights = []
    for cause, count in top_causes[:3]:
        cause_insights.append(
            {
                "cause": cause,
                "count": count,
                "insight": insight_text.get(cause, ""),
            }
        )

    totals_rows: list[dict[str, object]] = []
    for (cause, order), stats in totals_map.items():
        count = int(stats["count"])
        avg_amp = stats["amp_sum"] / max(1.0, stats["count"])
        totals_rows.append(
            {
                "cause": cause,
                "order": order,
                "count": count,
                "avg_amplitude_g": avg_amp,
            }
        )
    totals_rows.sort(key=lambda r: (-int(r["count"]), str(r["cause"]), str(r["order"])))

    breakdown_rows: list[dict[str, object]] = []
    for row in totals_rows[:6]:
        key = (str(row["cause"]), str(row["order"]))
        by_speed = breakdown_map.get(key, {})
        speed_rows: list[dict[str, object]] = []
        for speed_label, stats in sorted(
            by_speed.items(),
            key=lambda item: _speed_bin_sort_key(item[0]),
        ):
            count = int(stats["count"])
            range_count = max(count, speed_bin_totals.get(speed_label, 0))
            speed_rows.append(
                {
                    "speed_range": speed_label,
                    "count": count,
                    "range_count": range_count,
                    "range_time_s": range_count * sample_interval_s,
                    "percentage": (count / range_count * 100.0) if range_count else 0.0,
                    "avg_amplitude_g": (stats["amp_sum"] / max(1.0, stats["count"])),
                }
            )
        breakdown_rows.append(
            {
                "cause": row["cause"],
                "order": row["order"],
                "rows": speed_rows,
            }
        )

    if totals_rows:
        primary = totals_rows[0]
        primary_order = str(primary["order"])
        primary_cause = str(primary["cause"])
        if primary_order in {"1st", "2nd", "3rd"}:
            primary_title = f"{primary_order} Order {primary_cause}"
        else:
            primary_title = primary_cause
        primary_definition = insight_text.get(
            primary_cause,
            "Repair the primary vibration first, then re-test for additional vibration signatures.",
        )
    else:
        primary_title = "No dominant vibration detected"
        primary_definition = (
            "Collect a longer run with stable speed to improve diagnosis confidence."
        )

    report_dt = datetime.now(UTC)
    vehicle_data = {
        "Clients Observed": len([c for c in clients if c]),
        "Peak Frequency Mean (Hz)": f"{mean(peak_hz):.2f}" if peak_hz else "--",
        "Peak Amplitude Mean (g)": f"{mean(peak_amp):.4f}" if peak_amp else "--",
        "Average Speed (km/h)": f"{mean(speed_kmh_vals):.1f}" if speed_kmh_vals else "--",
        "Maximum Speed (km/h)": f"{max(speed_kmh_vals):.1f}" if speed_kmh_vals else "--",
        "Assumed Tire Diameter (in)": f"{ASSUMED_TIRE_DIAMETER_IN:.2f}",
    }
    settings = {
        "Speed Bin Width (km/h)": str(SPEED_BIN_WIDTH_KMH),
        "Order Matching Tolerance": f"{ORDER_TOLERANCE * 100:.0f}%",
        "Sample Interval Used (s)": f"{sample_interval_s:.3f}",
        "Detection Source": "peak1_hz / peak1_amp from logged axis metrics",
    }

    return {
        "file_name": csv_path.name,
        "rows": rows,
        "clients": sorted([c for c in clients if c]),
        "duration_s": duration_s,
        "record_date": first_ts.isoformat() if first_ts else "",
        "report_date": report_dt.isoformat(),
        "record_length": _format_duration(duration_s),
        "sample_interval_s": sample_interval_s,
        "mean_peak1_hz": mean(peak_hz) if peak_hz else 0.0,
        "max_p2p": max(p2p_vals) if p2p_vals else 0.0,
        "dropped_frames_max": dropped_total_max,
        "top_causes": cause_insights,
        "diagnostic_result": {
            "title": primary_title,
            "definition": primary_definition,
        },
        "vehicle_data": vehicle_data,
        "relevant_settings": settings,
        "totals": totals_rows,
        "breakdown": breakdown_rows,
    }


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _fallback_pdf(summary: dict[str, object]) -> bytes:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    clients = summary.get("clients", [])
    client_text = ", ".join(clients) if isinstance(clients, list) and clients else "None"
    causes = summary.get("top_causes", [])

    lines = [
        "VibeSensor Run Report",
        "",
        f"Generated: {now}",
        f"Log File: {summary.get('file_name', '')}",
        f"Samples Logged: {summary.get('rows', 0)}",
        f"Duration (s): {float(summary.get('duration_s', 0.0)):.1f}",
        f"Clients: {client_text}",
        f"Mean Primary Peak (Hz): {float(summary.get('mean_peak1_hz', 0.0)):.2f}",
        f"Max Peak-to-Peak: {float(summary.get('max_p2p', 0.0)):.2f}",
        f"Max Dropped Frames: {int(summary.get('dropped_frames_max', 0))}",
        "",
        "Probable Insights:",
    ]
    if isinstance(causes, list) and causes:
        for idx, cause in enumerate(causes, start=1):
            if not isinstance(cause, dict):
                continue
            lines.append(
                f"{idx}. {cause.get('cause', 'Unknown')} ({cause.get('count', 0)} events): "
                f"{cause.get('insight', '')}"
            )
    else:
        lines.append("1. Not enough high-confidence vibration signatures in this run.")

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
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

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
    style_body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=9, leading=12)
    style_note = ParagraphStyle(
        "Note",
        parent=styles["BodyText"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#4f5d73"),
    )

    def mk_table(
        data: list[list[str]],
        col_widths: list[int] | None = None,
        header: bool = True,
    ) -> Table:
        table = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
        style = TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b9c7d5")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
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
        table.setStyle(style)
        return table

    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    record_date = summary.get("record_date") or "--"
    story = [
        Paragraph("NVH Diagnostic Report", style_title),
        mk_table(
            [
                ["Report Date", "Record Name", "Record Date", "Record Length"],
                [
                    str(report_date)[:19].replace("T", " "),
                    str(summary.get("file_name", "")),
                    str(record_date)[:19].replace("T", " "),
                    str(summary.get("record_length", "--")),
                ],
            ],
            col_widths=[120, 180, 120, 90],
        ),
        Paragraph("Vehicle Data", style_h2),
    ]

    vehicle_data = summary.get("vehicle_data", {})
    if isinstance(vehicle_data, dict):
        vd_rows = [["Field", "Value"]]
        for key, val in vehicle_data.items():
            vd_rows.append([str(key), str(val)])
        story.append(mk_table(vd_rows, col_widths=[220, 290]))

    story.extend([Paragraph("Relevant Settings", style_h2)])
    settings_data = summary.get("relevant_settings", {})
    if isinstance(settings_data, dict):
        rs_rows = [["Setting", "Value"]]
        for key, val in settings_data.items():
            rs_rows.append([str(key), str(val)])
        story.append(mk_table(rs_rows, col_widths=[220, 290]))

    diag = summary.get("diagnostic_result", {})
    if isinstance(diag, dict):
        story.extend(
            [
                Paragraph("Diagnostic Results", style_h2),
                Paragraph(
                    "Repair this primary vibration first, then re-test for additional signatures.",
                    style_note,
                ),
                Paragraph(f"<b>{diag.get('title', 'No primary diagnosis')}</b>", style_body),
                Paragraph(f"Definition: {diag.get('definition', '')}", style_note),
            ]
        )

    totals = summary.get("totals", [])
    story.append(Paragraph("Totals", style_h2))
    totals_rows = [["Vibration Category", "Order", "Times Detected", "Average Amplitude (g)"]]
    if isinstance(totals, list) and totals:
        for row in totals[:12]:
            if not isinstance(row, dict):
                continue
            totals_rows.append(
                [
                    str(row.get("cause", "")),
                    str(row.get("order", "")),
                    str(int(_as_float(row.get("count", 0), 0.0))),
                    f"{_as_float(row.get('avg_amplitude_g', 0.0), 0.0):.4f}",
                ]
            )
    else:
        totals_rows.append(["No dominant vibration signatures found.", "", "", ""])
    story.append(mk_table(totals_rows, col_widths=[250, 70, 95, 95]))

    story.extend(
        [
            PageBreak(),
            Paragraph("Vibration Breakdown By Vehicle Speed", style_h2),
            Paragraph(
                (
                    "The table below summarizes how often each vibration signature "
                    "was detected by speed range. "
                    "Count (Time) Spent in Range uses the observed logging interval from this run."
                ),
                style_note,
            ),
            Spacer(1, 6),
        ]
    )

    breakdown = summary.get("breakdown", [])
    if isinstance(breakdown, list) and breakdown:
        for section in breakdown[:4]:
            if not isinstance(section, dict):
                continue
            cause = str(section.get("cause", ""))
            order = str(section.get("order", ""))
            if order in {"1st", "2nd", "3rd"}:
                title = f"{order} Order {cause} Breakdown"
            else:
                title = f"{cause} Breakdown"
            story.append(Paragraph(title, style_h2))
            rows = [
                [
                    "Vehicle Speed",
                    "Count",
                    "Count (Time) Spent in Range",
                    "Percentage",
                    "Average Amplitude (g)",
                ]
            ]
            for b_row in section.get("rows", []):
                if not isinstance(b_row, dict):
                    continue
                range_count = int(_as_float(b_row.get("range_count", 0), 0.0))
                range_time_s = _as_float(b_row.get("range_time_s", 0), 0.0)
                rows.append(
                    [
                        str(b_row.get("speed_range", "--")),
                        str(int(_as_float(b_row.get("count", 0), 0.0))),
                        f"{range_count} ({_format_duration(range_time_s)})",
                        f"{_as_float(b_row.get('percentage', 0.0), 0.0):.2f}%",
                        f"{_as_float(b_row.get('avg_amplitude_g', 0.0), 0.0):.4f}",
                    ]
                )
            if len(rows) == 1:
                rows.append(["No speed-linked data available", "", "", "", ""])
            story.append(mk_table(rows, col_widths=[110, 70, 150, 80, 100]))
            story.append(Spacer(1, 6))
    else:
        story.append(Paragraph("No speed-linked breakdown available for this run.", style_body))

    story.extend(
        [
            Spacer(1, 8),
            Paragraph(
                (
                    "This report was generated by VibeSensor local diagnostics. "
                    "Use with physical inspection and road test validation."
                ),
                style_note,
            ),
        ]
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=28,
        rightMargin=28,
        topMargin=30,
        bottomMargin=24,
    )

    def draw_footer(canvas, document) -> None:  # pragma: no cover - formatting callback
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#5a6778"))
        canvas.drawString(document.leftMargin, 12, "VibeSensor Diagnostic Report")
        canvas.drawRightString(
            LETTER[0] - document.rightMargin,
            12,
            f"Page {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return buffer.getvalue()


def build_report_pdf(summary: dict[str, object]) -> bytes:
    try:
        return _reportlab_pdf(summary)
    except Exception:
        return _fallback_pdf(summary)
