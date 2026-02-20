"""PDF report builder – new 2-page diagnostic worksheet layout.

Page 1: Diagnostic worksheet (header, observed signature, systems with
         findings, next steps, data trust).
Page 2: Evidence & diagnostics (car visual, pattern evidence panel,
         diagnostic peaks table).
"""

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
from ..report_theme import REPORT_COLORS
from .pattern_parts import parts_for_pattern, why_parts_listed
from .pdf_diagram import car_location_diagram
from .pdf_document import build_pdf_document
from .pdf_helpers import (
    location_hotspots,
    make_card,
    styled_table,
)
from .strength_labels import certainty_label, strength_text

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _human_source(source: object, *, tr) -> str:  # type: ignore[type-arg]
    raw = str(source or "").strip().lower()
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


def _top_strength_db(summary: dict) -> float | None:  # type: ignore[type-arg]
    """Best vibration_strength_db from top cause or samples."""
    for cause in summary.get("top_causes", []):
        if not isinstance(cause, dict):
            continue
        for f in summary.get("findings", []):
            if not isinstance(f, dict):
                continue
            if f.get("finding_id") == cause.get("finding_id"):
                amp = f.get("amplitude_metric")
                if isinstance(amp, dict):
                    v = _as_float(amp.get("value"))
                    if v is not None:
                        return v
    # Fallback: pick max from sensor intensity
    for row in summary.get("sensor_intensity_by_location", []):
        if isinstance(row, dict):
            v = _as_float(row.get("p95_intensity_db"))
            if v is not None:
                return v
    return None


# ---------------------------------------------------------------------------
# Page 1 builders
# ---------------------------------------------------------------------------


def _build_header(summary, *, tr, text_fn, style_title, style_note, content_width):
    """Header bar: title, date/time, car metadata."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, TableStyle

    report_date = summary.get("report_date") or datetime.now(UTC).isoformat()
    date_str = str(report_date)[:19].replace("T", " ")

    metadata = summary.get("metadata", {}) if isinstance(summary.get("metadata"), dict) else {}
    car_name = str(metadata.get("car_name") or metadata.get("vehicle_name") or "").strip()
    car_type = str(metadata.get("car_type") or metadata.get("vehicle_type") or "").strip()
    car_info = ""
    if car_name or car_type:
        parts = [p for p in (car_name, car_type) if p]
        sep = " \u2014 "
        car_info = f"  |  {tr('CAR_LABEL')}: {escape(sep.join(parts))}"

    header = styled_table(
        [
            [
                Paragraph(f"<b>{tr('DIAGNOSTIC_WORKSHEET')}</b>", style_title),
                Paragraph(
                    f"{escape(date_str)}{car_info}",
                    style_note,
                ),
            ]
        ],
        col_widths=[content_width * 0.45, content_width * 0.55],
        header=False,
    )
    header.setStyle(
        TableStyle(
            [("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(REPORT_COLORS["surface"]))]
        )
    )
    return header


def _build_observed_signature(
    summary, *, tr, text_fn, lang, style_note, style_small, content_width
):
    """Observed signature block: primary system, strength, certainty + reason."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )

    if top_causes:
        tc = top_causes[0]
        primary_system = _human_source(
            tc.get("source") or tc.get("suspected_source"), tr=tr
        )
        primary_location = str(tc.get("strongest_location") or tr("UNKNOWN"))
        primary_speed = str(tc.get("strongest_speed_band") or tr("UNKNOWN"))
        conf = _as_float(tc.get("confidence")) or _as_float(
            tc.get("confidence_0_to_1")
        ) or 0.0
    else:
        primary_system = tr("UNKNOWN")
        primary_location = tr("UNKNOWN")
        primary_speed = tr("UNKNOWN")
        conf = 0.0

    db_val = _top_strength_db(summary)
    str_text = strength_text(db_val, lang=lang)

    steady = bool(speed_stats.get("steady_speed"))
    weak_spatial = bool(
        top_causes[0].get("weak_spatial_separation") if top_causes else False
    )
    sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    has_ref_gaps = any(
        str(f.get("finding_id", "")).startswith("REF_") for f in findings
    )

    cert_key, cert_label_text, cert_pct, cert_reason = certainty_label(
        conf,
        lang=lang,
        steady_speed=steady,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
    )

    rows = [
        [
            Paragraph(
                f"<b>{tr('PRIMARY_SYSTEM')}:</b> {escape(primary_system)}",
                style_note,
            ),
            Paragraph(
                f"<b>{tr('STRONGEST_SENSOR')}:</b> {escape(primary_location)}",
                style_note,
            ),
        ],
        [
            Paragraph(
                f"<b>{tr('SPEED_BAND')}:</b> {escape(primary_speed)}",
                style_note,
            ),
            Paragraph(
                f"<b>{tr('STRENGTH')}:</b> {escape(str_text)}",
                style_note,
            ),
        ],
        [
            Paragraph(
                f"<b>{tr('CERTAINTY_LABEL_FULL')}:</b> {escape(cert_label_text)} ({escape(cert_pct)})",
                style_note,
            ),
            Paragraph(
                f"<b>{tr('CERTAINTY_REASON')}:</b> {escape(cert_reason)}",
                style_note,
            ),
        ],
    ]

    sig_table = Table(rows, colWidths=[content_width * 0.48, content_width * 0.48])
    sig_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor(REPORT_COLORS["surface"]),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor(REPORT_COLORS["border"]),
                ),
            ]
        )
    )

    disclaimer = Paragraph(
        f"<i>{tr('PATTERN_SUGGESTION_DISCLAIMER')}</i>",
        style_small,
    )

    return [sig_table, Spacer(1, 3), disclaimer]


def _build_system_cards(summary, *, tr, text_fn, lang, style_note, style_small, content_width):
    """System cards: one per system with meaningful findings."""
    from xml.sax.saxutils import escape

    from reportlab.platypus import Paragraph, Table, TableStyle

    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]

    if not top_causes:
        return [Paragraph(tr("NO_SYSTEMS_WITH_FINDINGS"), style_note)]

    cards = []
    for cause in top_causes[:3]:
        src = cause.get("source") or cause.get("suspected_source") or "unknown"
        src_human = _human_source(src, tr=tr)
        location = str(cause.get("strongest_location") or tr("UNKNOWN"))
        sigs = cause.get("signatures_observed", [])
        pattern_text = ", ".join(str(s) for s in sigs[:3]) if sigs else tr("UNKNOWN")
        order_label = str(sigs[0]) if sigs else None
        parts = parts_for_pattern(str(src), order_label, lang=lang)
        parts_text = ", ".join(parts) if parts else "\u2014"
        conf = _as_float(cause.get("confidence")) or _as_float(
            cause.get("confidence_0_to_1")
        ) or 0.0
        _ck, _cl, _cp, cert_reason = certainty_label(conf, lang=lang)
        tone = cause.get("confidence_tone", "neutral")
        card = make_card(
            src_human,
            [
                Paragraph(
                    f"<b>{tr('STRONGEST_LOCATION')}:</b> {escape(location)}",
                    style_small,
                ),
                Paragraph(
                    f"<b>{tr('PATTERN_SUMMARY')}:</b> {escape(pattern_text)}",
                    style_small,
                ),
                Paragraph(
                    f"<b>{tr('COMMON_PARTS')}:</b> {escape(parts_text)}",
                    style_small,
                ),
                Paragraph(
                    f"<b>{tr('WHY_SHOWN')}:</b> {escape(cert_reason)}",
                    style_small,
                ),
            ],
            style_note=style_note,
            tone=tone,
        )
        cards.append(card)

    n = len(cards)
    card_w = (content_width / n) - 4
    row = Table([cards], colWidths=[card_w] * n)
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return [row]


def _build_next_steps(summary, *, tr, text_fn, lang, style_note, style_small):
    """Single next-steps section ordered by most likely cause."""
    from xml.sax.saxutils import escape

    from reportlab.platypus import Paragraph

    test_plan = [s for s in summary.get("test_plan", []) if isinstance(s, dict)]
    if not test_plan:
        return [Paragraph(tr("NO_NEXT_STEPS"), style_note)]

    items = []
    for idx, step in enumerate(test_plan[:5], start=1):
        what = str(step.get("what") or "")
        why = str(step.get("why") or "")
        line = f"<b>{idx}.</b> {escape(what)}"
        if why:
            line += f" \u2014 <i>{escape(why)}</i>"
        items.append(Paragraph(line, style_note))
    return items


def _build_data_trust(summary, *, tr, text_fn, style_note, style_small, content_width):
    """Compact data trust / run quality box."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    run_suitability = [
        r for r in summary.get("run_suitability", []) if isinstance(r, dict)
    ]
    if not run_suitability:
        return [Paragraph(tr("UNKNOWN"), style_note)]

    cells = []
    for item in run_suitability:
        check = str(item.get("check") or "")
        state = str(item.get("state") or "warn")
        icon = "\u2713" if state == "pass" else "\u26a0"
        state_label = tr("PASS") if state == "pass" else tr("WARN_SHORT")
        cells.append(
            Paragraph(
                f"<b>{escape(check)}:</b> {icon} {escape(state_label)}",
                style_small,
            )
        )

    n = len(cells)
    col_w = content_width / max(n, 1)
    trust_table = Table([cells], colWidths=[col_w] * n)
    trust_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor(REPORT_COLORS["surface"]),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor(REPORT_COLORS["border"]),
                ),
            ]
        )
    )
    return [trust_table]


# ---------------------------------------------------------------------------
# Page 2 builders
# ---------------------------------------------------------------------------


def _build_pattern_evidence_panel(
    summary, *, tr, text_fn, lang, style_note, style_small, panel_width
):
    """Compact pattern evidence panel for page 2."""
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    findings = [f for f in summary.get("findings", []) if isinstance(f, dict)]
    speed_stats = (
        summary.get("speed_stats", {}) if isinstance(summary.get("speed_stats"), dict) else {}
    )

    systems = [
        _human_source(c.get("source") or c.get("suspected_source"), tr=tr)
        for c in top_causes[:3]
    ]
    systems_text = ", ".join(systems) if systems else tr("UNKNOWN")

    location = (
        str(top_causes[0].get("strongest_location") or tr("UNKNOWN"))
        if top_causes
        else tr("UNKNOWN")
    )
    speed_band = (
        str(top_causes[0].get("strongest_speed_band") or tr("UNKNOWN"))
        if top_causes
        else tr("UNKNOWN")
    )

    db_val = _top_strength_db(summary)
    str_text = strength_text(db_val, lang=lang)

    conf = (
        _as_float(top_causes[0].get("confidence"))
        or _as_float(top_causes[0].get("confidence_0_to_1"))
        or 0.0
    ) if top_causes else 0.0

    steady = bool(speed_stats.get("steady_speed"))
    weak_spatial = bool(top_causes[0].get("weak_spatial_separation")) if top_causes else False
    sensor_count = int(_as_float(summary.get("sensor_count_used")) or 0)
    has_ref_gaps = any(str(f.get("finding_id", "")).startswith("REF_") for f in findings)

    _ck, cert_label_text, cert_pct, cert_reason = certainty_label(
        conf,
        lang=lang,
        steady_speed=steady,
        weak_spatial=weak_spatial,
        sensor_count=sensor_count,
        has_reference_gaps=has_ref_gaps,
    )

    origin = summary.get("most_likely_origin", {})
    interp = str(origin.get("explanation", "")) if isinstance(origin, dict) else ""

    src = str(
        (top_causes[0].get("source") or top_causes[0].get("suspected_source"))
        if top_causes
        else ""
    )
    sigs = top_causes[0].get("signatures_observed", []) if top_causes else []
    order_lbl = str(sigs[0]) if sigs else None
    why_text = why_parts_listed(src, order_lbl, lang=lang)

    rows = [
        [Paragraph(f"<b>{tr('MATCHED_SYSTEMS')}:</b> {escape(systems_text)}", style_note)],
        [Paragraph(f"<b>{tr('STRONGEST_LOCATION')}:</b> {escape(location)}", style_note)],
        [Paragraph(f"<b>{tr('SPEED_BAND')}:</b> {escape(speed_band)}", style_note)],
        [Paragraph(f"<b>{tr('STRENGTH')}:</b> {escape(str_text)}", style_note)],
        [
            Paragraph(
                f"<b>{tr('CERTAINTY_LABEL_FULL')}:</b> {escape(cert_label_text)} ({escape(cert_pct)}) "
                f"\u2014 {escape(cert_reason)}",
                style_note,
            )
        ],
    ]
    if weak_spatial:
        rows.append(
            [
                Paragraph(
                    f"<b>\u26a0 {tr('WARNING_LABEL')}:</b> {escape(cert_reason)}",
                    style_small,
                )
            ]
        )
    if interp:
        rows.append(
            [Paragraph(f"<b>{tr('INTERPRETATION')}:</b> {escape(interp)}", style_small)]
        )
    rows.append(
        [Paragraph(f"<b>{tr('WHY_PARTS_LISTED')}:</b> {escape(why_text)}", style_small)]
    )

    panel = Table(rows, colWidths=[panel_width - 16])
    panel.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor(REPORT_COLORS["surface"]),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.HexColor(REPORT_COLORS["border"]),
                ),
                ("ROUNDEDCORNERS", [6, 6, 6, 6]),
            ]
        )
    )
    return panel


def _build_diagnostic_peaks_table(
    summary, *, tr, text_fn, lang, style_note, style_small, table_width
):
    """Diagnostic-first peaks table (system-relevance oriented)."""
    plots = summary.get("plots", {}) if isinstance(summary.get("plots"), dict) else {}

    header = [
        tr("RANK"),
        tr("SYSTEM"),
        tr("FREQUENCY_HZ"),
        tr("ORDER_LABEL"),
        tr("AMP_G"),
        tr("SPEED_BAND"),
        tr("RELEVANCE"),
    ]
    rows = [header]

    peaks_table_items = plots.get("peaks_table", [])
    if isinstance(peaks_table_items, list) and peaks_table_items:
        for row in peaks_table_items[:8]:
            if not isinstance(row, dict):
                continue
            rank = str(int(_as_float(row.get("rank")) or 0))
            freq = f"{(_as_float(row.get('frequency_hz')) or 0.0):.1f}"
            order = str(row.get("order_label") or "\u2014")
            amp = f"{(_as_float(row.get('max_amp_g')) or 0.0):.4f}"
            speed = str(row.get("typical_speed_band") or "\u2014")

            order_lower = order.lower()
            if "wheel" in order_lower:
                system = tr("SOURCE_WHEEL_TIRE")
                relevance = order
            elif "engine" in order_lower:
                system = tr("SOURCE_ENGINE")
                relevance = order
            elif "driveshaft" in order_lower or "drive" in order_lower:
                system = tr("SOURCE_DRIVELINE")
                relevance = order
            else:
                system = "\u2014"
                relevance = "\u2014"

            rows.append([rank, system, freq, order, amp, speed, relevance])
    else:
        rows.append(["\u2014", "\u2014", "\u2014", "\u2014", "\u2014", "\u2014", tr("UNKNOWN")])

    col_w = table_width / 7.0
    return styled_table(
        rows,
        col_widths=[
            int(col_w * 0.6),
            int(col_w * 1.2),
            int(col_w * 0.9),
            int(col_w * 1.1),
            int(col_w * 0.8),
            int(col_w * 1.1),
            int(col_w * 1.3),
        ],
    )


# ---------------------------------------------------------------------------
# Main report assembly
# ---------------------------------------------------------------------------


def _reportlab_pdf(summary: dict[str, object]) -> bytes:  # noqa: C901
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

    git_sha = str(os.getenv("GIT_SHA", "")).strip()
    version_marker = f"v{__version__} ({git_sha[:8]})" if git_sha else f"v{__version__}"

    findings = summary.get("findings", [])
    location_rows, _, _, _ = location_hotspots(
        summary.get("samples", []),
        findings,
        tr=tr,
        text_fn=text_fn,
    )

    # == PAGE 1: Diagnostic Worksheet ======================================
    story: list[object] = []

    header = _build_header(
        summary,
        tr=tr,
        text_fn=text_fn,
        style_title=style_title,
        style_note=style_note,
        content_width=content_width,
    )
    story.append(header)
    story.append(Spacer(1, 6))

    story.append(Paragraph(f"<b>{tr('OBSERVED_SIGNATURE')}</b>", style_h2))
    sig_elements = _build_observed_signature(
        summary,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_note=style_note,
        style_small=style_small,
        content_width=content_width,
    )
    story.extend(sig_elements)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>{tr('SYSTEMS_WITH_FINDINGS')}</b>", style_h3))
    story.append(Spacer(1, 4))
    cards = _build_system_cards(
        summary,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_note=style_note,
        style_small=style_small,
        content_width=content_width,
    )
    story.extend(cards)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>{tr('NEXT_STEPS')}</b>", style_h3))
    story.append(Spacer(1, 3))
    steps = _build_next_steps(
        summary,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_note=style_note,
        style_small=style_small,
    )
    story.extend(steps)
    story.append(Spacer(1, 8))

    story.append(Paragraph(f"<b>{tr('DATA_TRUST')}</b>", style_h3))
    story.append(Spacer(1, 3))
    trust = _build_data_trust(
        summary,
        tr=tr,
        text_fn=text_fn,
        style_note=style_note,
        style_small=style_small,
        content_width=content_width,
    )
    story.extend(trust)

    # == PAGE 2: Evidence & Diagnostics ====================================
    story.append(PageBreak())
    story.append(Paragraph(tr("EVIDENCE_DIAGNOSTICS"), style_title))
    story.append(Spacer(1, 4))

    left_width = content_width * 0.42
    right_width = content_width * 0.55
    gap_width = content_width - left_width - right_width

    top_causes = [c for c in summary.get("top_causes", []) if isinstance(c, dict)]
    diagram = car_location_diagram(
        top_causes or (findings if isinstance(findings, list) else []),
        summary,
        location_rows,
        content_width=content_width,
        tr=tr,
        text_fn=text_fn,
        diagram_width=left_width,
    )

    evidence_panel = _build_pattern_evidence_panel(
        summary,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_note=style_note,
        style_small=style_small,
        panel_width=right_width,
    )

    peaks_heading = Paragraph(f"<b>{tr('DIAGNOSTIC_PEAKS')}</b>", style_h3)
    peaks_table = _build_diagnostic_peaks_table(
        summary,
        tr=tr,
        text_fn=text_fn,
        lang=lang,
        style_note=style_note,
        style_small=style_small,
        table_width=right_width,
    )

    right_col = Table(
        [
            [Paragraph(f"<b>{tr('PATTERN_EVIDENCE')}</b>", style_h3)],
            [evidence_panel],
            [Spacer(1, 6)],
            [peaks_heading],
            [peaks_table],
        ],
        colWidths=[right_width],
    )
    right_col.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )

    page2_layout = Table(
        [[diagram, right_col]],
        colWidths=[left_width + gap_width, right_width],
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
    """Build a 2-page diagnostic-worksheet PDF from a run summary dict."""
    try:
        return _reportlab_pdf(summary)
    except Exception as exc:
        LOGGER.error("ReportLab PDF generation failed.", exc_info=True)
        raise RuntimeError("ReportLab PDF generation failed") from exc
