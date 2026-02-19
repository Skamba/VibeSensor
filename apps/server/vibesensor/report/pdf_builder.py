"""PDF report builder – assembles pages from helper modules."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from .. import __version__
from ..report_analysis import (
    _as_float,
    _normalize_lang,
)
from ..report_i18n import tr as _tr
from ..report_theme import (
    REPORT_COLORS,
    REPORT_PLOT_COLORS,
)
from .pdf_charts import line_plot
from .pdf_diagram import car_location_diagram
from .pdf_document import build_pdf_document
from .pdf_helpers import (
    compact_note_panel,
    confidence_pill_html,
    human_frequency_text,
    human_source,
    location_hotspots,
    make_card,
    ptext,
    styled_table,
)
from .pdf_sections import (
    build_data_quality,
    build_detailed_findings,
    build_metadata,
    build_sensor_stats,
    build_speed_analysis,
)

LOGGER = logging.getLogger(__name__)


def _reportlab_pdf(summary: dict[str, object]) -> bytes:  # noqa: C901
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    page_size = landscape(A4)
    left_margin = 28
    right_margin = 28
    top_margin = 30
    bottom_margin = 24
    content_width = page_size[0] - left_margin - right_margin
    lang = _normalize_lang(summary.get("lang"))

    def tr(key: str, **kwargs: object) -> str:
        return _tr(lang, key, **kwargs)

    def text_fn(en_text: str, nl_text: str) -> str:
        return nl_text if lang == "nl" else en_text

    # ── Typography ────────────────────────────────────────────────────
    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleMain",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        spaceAfter=6,
    )
    style_h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
        spaceAfter=4,
        spaceBefore=8,
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
    style_body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8.5, leading=11)
    style_note = ParagraphStyle(
        "Note",
        parent=styles["BodyText"],
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor(REPORT_COLORS["text_secondary"]),
    )
    style_small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=7,
        leading=9,
        textColor=colors.HexColor(REPORT_COLORS["text_muted"]),
    )
    style_table_head = ParagraphStyle(
        "TableHead",
        parent=style_note,
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.0,
        textColor=colors.HexColor(REPORT_COLORS["text_primary"]),
    )

    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    version_marker = f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"
    quality = summary.get("data_quality", {})
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )
    steady_speed = bool(speed_stats.get("steady_speed"))
    findings = summary.get("findings", [])
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}

    location_rows, _, _, _ = location_hotspots(
        summary.get("samples", []),
        findings,
        tr=tr,
        text_fn=text_fn,
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
    top_confidence = (
        _as_float(top_finding.get("confidence_0_to_1")) if isinstance(top_finding, dict) else 0.0
    )

    if any(fid.startswith("REF_") for fid in finding_ids):
        overall_status = tr("STATUS_REFERENCE_GAPS")
        status_tone = "warn"
    elif (top_confidence or 0.0) >= 0.7:
        overall_status = tr("STATUS_ACTIONABLE_HIGH_CONFIDENCE")
        status_tone = "success"
    else:
        overall_status = tr("STATUS_PRELIMINARY")
        status_tone = "neutral"

    top_causes = [item for item in summary.get("top_causes", []) if isinstance(item, dict)]
    test_plan = [item for item in summary.get("test_plan", []) if isinstance(item, dict)]
    run_suitability = [
        item for item in summary.get("run_suitability", []) if isinstance(item, dict)
    ]

    lang_indicator = "NL" if lang == "nl" else "EN"
    header_bar = styled_table(
        [
            [
                Paragraph(f"<b>{tr('NVH_DIAGNOSTIC_REPORT')}</b>", style_h2),
                Paragraph(
                    f"<b>{tr('REPORT_DATE')}:</b> {str(report_date)[:19].replace('T', ' ')}  "
                    f"<b>{tr('RUN_ID')}:</b> {summary.get('run_id', '')}  "
                    f"<b>{lang_indicator}</b>",
                    style_note,
                ),
            ],
        ],
        col_widths=[content_width * 0.45, content_width * 0.55],
        header=False,
    )
    header_bar.setStyle(
        TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(REPORT_COLORS["surface"]))])
    )

    card_status = make_card(
        tr("OVERALL_STATUS"),
        [Paragraph(overall_status, style_note)],
        style_note=style_note,
        tone=status_tone,
    )

    if top_causes:
        tc = top_causes[0]
        tc_source = human_source(tc.get("source") or tc.get("suspected_source"), tr=tr)
        tc_conf = _as_float(tc.get("confidence")) or _as_float(tc.get("confidence_0_to_1")) or 0.0
        tc_pill = confidence_pill_html(tc_conf, tr=tr, show_percent=False)
        tc_loc = str(tc.get("strongest_location") or tr("UNKNOWN"))
        tc_speed = str(tc.get("strongest_speed_band") or tr("UNKNOWN"))
        cause_tone = tc.get("confidence_tone", "neutral")
        card_cause = make_card(
            tr("TOP_SUSPECTED_CAUSE"),
            [
                Paragraph(f"<b>{escape(tc_source)}</b> {tc_pill}", style_note),
                Paragraph(
                    f"{tr('STRONGEST_LOCATION')}: {escape(tc_loc)}<br/>"
                    f"{tr('STRONGEST_SPEED_BAND')}: {escape(tc_speed)}",
                    style_small,
                ),
            ],
            style_note=style_note,
            tone=cause_tone,
        )
    else:
        card_cause = make_card(
            tr("TOP_SUSPECTED_CAUSE"),
            [Paragraph(tr("UNKNOWN"), style_note)],
            style_note=style_note,
            tone="neutral",
        )

    card_conditions = make_card(
        tr("RUN_CONDITIONS"),
        [
            Paragraph(
                (
                    f"{tr('DURATION')}: "
                    f"{summary.get('record_length', tr('MISSING_DURATION_UNAVAILABLE'))}<br/>"
                    f"{text_fn('Speed range', 'Snelheidsbereik')}: "
                    f"{(_as_float(speed_stats.get('min_kmh')) or 0.0):.1f}"
                    f"\u2013{(_as_float(speed_stats.get('max_kmh')) or 0.0):.1f} km/h<br/>"
                    f"{text_fn('Sample rate', 'Bemonsteringsfrequentie')}: "
                    f"{(_as_float(summary.get('raw_sample_rate_hz')) or 0.0):.0f} Hz<br/>"
                    f"{text_fn('Sensors', 'Sensoren')}: "
                    f"{int(_as_float(summary.get('sensor_count_used')) or 0)}"
                ),
                style_note,
            )
        ],
        style_note=style_note,
        tone="neutral",
    )

    card_w = content_width / 3.0 - 4
    cards_row = Table(
        [[card_status, card_cause, card_conditions]],
        colWidths=[card_w, card_w, card_w],
    )
    cards_row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    primary_speed_band = str(top_finding.get("strongest_speed_band") or "").strip()
    if not primary_speed_band and top_causes:
        primary_speed_band = str(top_causes[0].get("strongest_speed_band") or "").strip()
    primary_frequency = str(top_finding.get("frequency_hz_or_order") or "").strip()

    if not test_plan:
        test_plan = [
            {
                "what": tr("COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS"),
                "why": tr("NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA"),
                "certainty_0_to_1": "0.0",
                "speed_band": primary_speed_band,
                "frequency_hz_or_order": primary_frequency,
            }
        ]
    check_first_header = [
        text_fn("Step", "Stap"),
        tr("WHAT"),
        tr("WHY_SHORT"),
        tr("CERTAINTY"),
        tr("SPEED"),
        tr("FREQUENCY"),
    ]
    check_first_rows = [check_first_header]
    for idx, step in enumerate(test_plan[:5], start=1):
        certainty = _as_float(step.get("certainty_0_to_1"))
        if certainty is None:
            certainty = _as_float(step.get("confidence_0_to_1"))
        if certainty is None:
            certainty = top_confidence
        certainty = max(0.0, min(1.0, certainty or 0.0))
        certainty_text = f"{certainty:.2f}"
        speed_text = str(
            step.get("speed_band")
            or step.get("strongest_speed_band")
            or primary_speed_band
            or tr("UNKNOWN")
        )
        frequency_text = human_frequency_text(
            step.get("frequency_hz_or_order") or primary_frequency or tr("UNKNOWN"),
            tr=tr,
        )
        check_first_rows.append(
            [
                str(idx),
                Paragraph(str(step.get("what") or ""), style_note),
                Paragraph(str(step.get("why") or ""), style_note),
                Paragraph(certainty_text, style_small),
                Paragraph(speed_text, style_small),
                Paragraph(frequency_text, style_small),
            ]
        )

    strongest_loc_text = str(location_rows[0]["location"]) if location_rows else tr("UNKNOWN")
    strongest_peak_g = float(location_rows[0]["peak_g"]) if location_rows else 0.0
    dominance_ratio = 1.0
    if location_rows and len(location_rows) > 1:
        second = float(location_rows[1]["peak_g"])
        if second > 0:
            dominance_ratio = strongest_peak_g / second

    ref_complete = any(
        str(item.get("state") or "") == "pass"
        for item in run_suitability
        if "reference" in str(item.get("check") or "").lower()
    )
    ref_text_val = (
        text_fn("Complete", "Compleet") if ref_complete else text_fn("Incomplete", "Incompleet")
    )

    evidence_snapshot_rows = [
        [tr("STRONGEST_LOCATION"), f"{strongest_loc_text} ({strongest_peak_g:.4f} g)"],
        [tr("DOMINANCE_RATIO"), f"{dominance_ratio:.2f}x"],
        [
            tr("STRONGEST_SPEED_BAND"),
            str(top_causes[0].get("strongest_speed_band") or tr("UNKNOWN"))
            if top_causes
            else tr("UNKNOWN"),
        ],
        [tr("REFERENCE_COMPLETENESS"), ref_text_val],
    ]
    primary_source_text = (
        human_source(top_causes[0].get("source") or top_causes[0].get("suspected_source"), tr=tr)
        if top_causes
        else tr("UNKNOWN")
    )
    primary_location_text = (
        str(top_causes[0].get("strongest_location") or tr("UNKNOWN"))
        if top_causes
        else tr("UNKNOWN")
    )
    primary_finding_line = text_fn("Primary finding", "Primaire bevinding")
    primary_finding_value = f"{primary_source_text} @ {primary_location_text}"

    story: list[object] = [
        Paragraph(tr("WORKSHOP_SUMMARY"), style_title),
        header_bar,
        Spacer(1, 6),
        cards_row,
        Spacer(1, 8),
        Paragraph(
            f"<b>{escape(primary_finding_line)}:</b> {escape(primary_finding_value)}",
            style_note,
        ),
        Spacer(1, 6),
        Paragraph(f"<b>{tr('WHAT_TO_CHECK_FIRST')}</b>", style_h3),
        styled_table(
            check_first_rows,
            col_widths=[30, 180, 180, 95, 115, 110],
        ),
        Spacer(1, 6),
        Paragraph(f"<b>{tr('EVIDENCE_SNAPSHOT')}</b>", style_h3),
        styled_table(
            [
                [
                    ptext(
                        r[0],
                        style_table_head=style_table_head,
                        style_note=style_note,
                        header=True,
                    ),
                    ptext(r[1], style_table_head=style_table_head, style_note=style_note),  # noqa: E501
                ]
                for r in evidence_snapshot_rows
            ],
            col_widths=[180, 530],
            header=False,
        ),
    ]

    warnings = summary.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        story.append(Spacer(1, 4))
        story.append(
            Paragraph(
                f"<b>{tr('INPUT_WARNINGS')}</b><br/>{'<br/>'.join(str(w) for w in warnings)}",
                style_note,
            )
        )

    story.append(PageBreak())
    story.append(Paragraph(tr("EVIDENCE_AND_HOTSPOTS"), style_title))
    left_width = content_width * 0.45
    right_width = content_width * 0.55

    diagram = car_location_diagram(
        top_causes or findings,
        summary,
        location_rows,
        content_width=content_width,
        tr=tr,
        text_fn=text_fn,
        diagram_width=left_width,
    )

    fft_points = plots.get("fft_spectrum", [])
    fft_chart = None
    if isinstance(fft_points, list) and fft_points:
        fft_chart = line_plot(
            title=text_fn("FFT spectrum (global)", "FFT-spectrum (globaal)"),
            x_label=tr("FREQUENCY_HZ"),
            y_label=text_fn("amplitude (g)", "amplitude (g)"),
            series=[
                (
                    text_fn("max amplitude", "maximale amplitude"),
                    REPORT_PLOT_COLORS["vibration"],
                    fft_points,
                )
            ],
            content_width=content_width,
            tr=tr,
            width=right_width,
            height=168,
        )

    peaks_rows = [
        [
            text_fn("Rank", "Rang"),
            text_fn("Frequency (Hz)", "Frequentie (Hz)"),
            text_fn("Order", "Orde"),
            text_fn("Max amp (g)", "Max amp (g)"),
            text_fn("Typical speed", "Typische snelheid"),
        ]
    ]
    peaks_table_items = plots.get("peaks_table", [])
    if isinstance(peaks_table_items, list) and peaks_table_items:
        for row in peaks_table_items[:10]:
            if not isinstance(row, dict):
                continue
            peaks_rows.append(
                [
                    str(int(_as_float(row.get("rank")) or 0)),
                    f"{(_as_float(row.get('frequency_hz')) or 0.0):.1f}",
                    str(row.get("order_label") or "-"),
                    f"{(_as_float(row.get('max_amp_g')) or 0.0):.4f}",
                    str(row.get("typical_speed_band") or "-"),
                ]
            )
    else:
        peaks_rows.append(["-", "-", "-", "-", tr("PLOT_NO_DATA_AVAILABLE")])

    peaks_table_block = styled_table(peaks_rows, col_widths=[32, 72, 68, 72, 138])

    left_column = Table(
        [
            [diagram],
            [Paragraph(f"<b>{text_fn('Top Peaks', 'Top pieken')}</b>", style_h3)],
            [peaks_table_block],
        ],
        colWidths=[left_width],
    )
    left_column.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    right_blocks: list[object] = []
    if fft_chart is not None:
        right_blocks.append(fft_chart)
    else:
        right_blocks.append(
            compact_note_panel(
                text_fn("FFT spectrum (global)", "FFT-spectrum (globaal)"),
                tr("PLOT_NO_DATA_AVAILABLE"),
                right_width,
                style_note=style_note,
                height=168,
            )
        )
    right_column = Table([[item] for item in right_blocks], colWidths=[right_width])
    right_column.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    page2_layout = Table(
        [[left_column, right_column]],
        colWidths=[left_width, right_width],
    )
    page2_layout.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(page2_layout)

    build_sensor_stats(
        summary=summary,
        story=story,
        tr=tr,
        text_fn=text_fn,
        style_h2=style_h2,
        style_note=style_note,
        style_small=style_small,
    )
    build_speed_analysis(
        summary=summary,
        story=story,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_h2=style_h2,
        style_h3=style_h3,
        style_body=style_body,
        style_note=style_note,
        steady_speed=steady_speed,
        plots=plots,
    )
    build_data_quality(
        summary=summary,
        story=story,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_h2=style_h2,
        style_h3=style_h3,
        style_body=style_body,
        quality=quality,
        run_suitability=run_suitability,
    )
    build_metadata(
        summary=summary,
        story=story,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_h2=style_h2,
        style_h3=style_h3,
    )
    build_detailed_findings(
        findings=findings,
        story=story,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_h2=style_h2,
        style_note=style_note,
        style_table_head=style_table_head,
    )

    return build_pdf_document(
        story=story,
        page_size=page_size,
        left_margin=left_margin,
        right_margin=right_margin,
        top_margin=top_margin,
        bottom_margin=bottom_margin,
        version_marker=version_marker,
        tr=tr,
    )


def build_report_pdf(summary: dict[str, object]) -> bytes:
    try:
        return _reportlab_pdf(summary)
    except Exception as exc:
        LOGGER.error("ReportLab PDF generation failed.", exc_info=True)
        raise RuntimeError("ReportLab PDF generation failed") from exc
