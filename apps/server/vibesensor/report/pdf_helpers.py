"""PDF report helper functions – text formatters, UI components, and utilities."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from ..report_i18n import variants as _tr_variants
from ..report_theme import (
    CARD_PADDING,
    CARD_RADIUS,
    FINDING_SOURCE_COLORS,
    REPORT_COLORS,
)
from ..runlog import as_float_or_none as _as_float
from .helpers import _required_text
from .summary import confidence_label

if TYPE_CHECKING:
    from collections.abc import Callable


# ── Pure helpers (no external deps) ──────────────────────────────────────


def _tone_to_pill_tone(tone: str) -> str:
    """Map card/confidence tones to pill theme keys (high/medium/low)."""
    tone_map = {"success": "high", "warn": "medium", "neutral": "low", "error": "low"}
    return tone_map.get(tone, "low")


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


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    txt = value.strip().lstrip("#")
    return (int(txt[0:2], 16), int(txt[2:4], 16), int(txt[4:6], 16))


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def color_blend(a: str, b: str, t: float) -> str:
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


def _canonical_location(raw: object) -> str:
    token = str(raw or "").strip().lower().replace("_", "-")
    compact = "".join(ch for ch in token if ch.isalnum())
    if ("front" in token and "left" in token and "wheel" in token) or compact in {
        "frontleft",
        "frontleftwheel",
        "fl",
        "flwheel",
    }:
        return "front-left wheel"
    if ("front" in token and "right" in token and "wheel" in token) or compact in {
        "frontright",
        "frontrightwheel",
        "fr",
        "frwheel",
    }:
        return "front-right wheel"
    if ("rear" in token and "left" in token and "wheel" in token) or compact in {
        "rearleft",
        "rearleftwheel",
        "rl",
        "rlwheel",
    }:
        return "rear-left wheel"
    if ("rear" in token and "right" in token and "wheel" in token) or compact in {
        "rearright",
        "rearrightwheel",
        "rr",
        "rrwheel",
    }:
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


# ── Text helpers (need tr / text callbacks) ──────────────────────────────


def human_source(source: object, *, tr: Callable[..., str]) -> str:
    raw = str(source or "").strip().lower()
    mapping = {
        "wheel/tire": tr("SOURCE_WHEEL_TIRE"),
        "driveline": tr("SOURCE_DRIVELINE"),
        "engine": tr("SOURCE_ENGINE"),
        "body resonance": tr("SOURCE_BODY_RESONANCE"),
        "unknown": tr("UNKNOWN"),
    }
    return mapping.get(raw, raw.replace("_", " ").title() if raw else tr("UNKNOWN"))


def human_finding_title(finding: dict[str, object], index: int, *, tr: Callable[..., str]) -> str:
    fid = str(finding.get("finding_id", "")).strip().upper()
    source = human_source(finding.get("suspected_source"), tr=tr)
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


def human_frequency_text(value: object, *, tr: Callable[..., str]) -> str:
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


def human_amp_text(amp: object, *, tr: Callable[..., str], text_fn: Callable[..., str]) -> str:
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
        "vibration_strength_db": text_fn("Vibration strength", "Trillingssterkte"),
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


def confidence_pill_html(
    conf_0_to_1: float, *, tr: Callable[..., str], show_percent: bool = False
) -> str:
    """Return a small HTML snippet for the confidence pill."""
    label_key, tone, pct_text = confidence_label(conf_0_to_1)
    label = tr(label_key)
    pill_tone = _tone_to_pill_tone(tone)
    pill_bg = REPORT_COLORS.get(f"pill_{pill_tone}_bg", REPORT_COLORS["pill_low_bg"])
    pill_text_color = REPORT_COLORS.get(f"pill_{pill_tone}_text", REPORT_COLORS["pill_low_text"])
    html = (
        f'<font color="{pill_text_color}">'
        f'<span backColor="{pill_bg}"> {escape(label)} </span></font>'
    )
    if show_percent:
        html += f' <font size="6" color="{REPORT_COLORS["text_muted"]}">{escape(pct_text)}</font>'
    return html


def req_text(value: object, consequence_key: str, *, tr: Callable[..., str], lang: str) -> str:
    return _required_text(value, tr(consequence_key), lang=lang)


def location_hotspots(
    samples_obj: object,
    findings_obj: object,
    *,
    tr: Callable[..., str],
    text_fn: Callable[..., str],
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
            amp = _as_float(sample.get("vibration_strength_db"))
            if amp is not None and amp > 0:
                amp_by_location[location].append(amp)

    hotspot_rows: list[dict[str, object]] = []
    for location, amps in amp_by_location.items():
        hotspot_rows.append(
            {
                "location": location,
                "count": len(amps),
                "peak_g": max(amps),
                "mean_g": mean(amps),
            }
        )
    hotspot_rows.sort(key=lambda row: (float(row["peak_g"]), float(row["mean_g"])), reverse=True)
    if not hotspot_rows:
        return (
            [],
            tr("NO_USABLE_AMPLITUDE_BY_LOCATION_DATA_WAS_FOUND"),
            0,
            len(all_locations),
        )

    active_count = len(hotspot_rows)
    monitored_count = len(all_locations)
    strongest = hotspot_rows[0]
    strongest_loc = str(strongest["location"])
    strongest_peak = float(strongest["peak_g"])
    summary_text = tr(
        "VIBRATION_SIGNATURE_WAS_DETECTED_AT_ACTIVE_COUNT_OF",
        active_count=active_count,
        monitored_count=monitored_count,
        strongest_loc=strongest_loc,
        strongest_peak=strongest_peak,
    )
    if matched_points:
        summary_text = text_fn(
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
        if len(hotspot_rows) >= 2:
            second_peak = float(hotspot_rows[1]["peak_g"])
            if second_peak > 0 and (strongest_peak / second_peak) >= 1.15:
                summary_text += tr(
                    "SINCE_ALL_SENSORS_SAW_THE_SIGNATURE_BUT_STRONGEST",
                    strongest_loc=strongest_loc,
                )
    return hotspot_rows, summary_text, active_count, monitored_count


# ── UI component helpers (need reportlab – lazy-imported) ────────────────


def ptext(
    value: object,
    *,
    style_table_head: Any,
    style_note: Any,
    header: bool = False,
    break_underscores: bool = False,
) -> Any:
    from reportlab.platypus import Paragraph

    txt = escape(str(value if value is not None else ""))
    txt = txt.replace("\n", "<br/>")
    if break_underscores:
        txt = txt.replace("_", "_<br/>")
    return Paragraph(txt, style_table_head if header else style_note)


def human_list(
    items: object,
    *,
    tr: Callable[..., str],
    style_table_head: Any,
    style_note: Any,
) -> Any:
    from reportlab.platypus import Paragraph

    if not isinstance(items, list):
        return ptext(tr("NONE_LISTED"), style_table_head=style_table_head, style_note=style_note)
    cleaned = [str(v).strip() for v in items if str(v).strip()]
    if not cleaned:
        return ptext(tr("NONE_LISTED"), style_table_head=style_table_head, style_note=style_note)
    lines = [f"{i + 1}. {escape(val)}" for i, val in enumerate(cleaned)]
    return Paragraph("<br/>".join(lines), style_note)


def styled_table(
    data: list[list[object]],
    col_widths: list[int] | None = None,
    header: bool = True,
    zebra: bool = True,
    repeat_rows: int | None = None,
) -> Any:
    """Create a polished table with optional header bg, zebra, and light separators."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table = Table(
        data,
        colWidths=col_widths,
        repeatRows=repeat_rows if repeat_rows is not None else (1 if header else 0),
    )
    cmds: list[tuple[object, ...]] = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
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
            0.3,
            colors.HexColor(REPORT_COLORS["table_row_border"]),
        ),
    ]
    if header:
        cmds.extend(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.HexColor(REPORT_COLORS["table_header_bg"]),
                ),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(REPORT_COLORS["text_primary"])),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    if zebra and len(data) > 2:
        for row_idx in range(2 if header else 1, len(data), 2):
            cmds.append(
                (
                    "BACKGROUND",
                    (0, row_idx),
                    (-1, row_idx),
                    colors.HexColor(REPORT_COLORS["table_zebra_bg"]),
                )
            )
    table.setStyle(TableStyle(cmds))
    return table


def make_card(
    title: str,
    body_flowables: list[object],
    *,
    style_note: Any,
    badge: str | None = None,
    tone: str = "neutral",
) -> Any:
    """Build a Material-style card with title, optional badge, and body flowables."""
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    tone_bg = REPORT_COLORS.get(f"card_{tone}_bg", REPORT_COLORS["card_neutral_bg"])
    tone_border = REPORT_COLORS.get(f"card_{tone}_border", REPORT_COLORS["card_neutral_border"])
    title_html = f"<b>{escape(title)}</b>"
    if badge:
        pill_tone = _tone_to_pill_tone(tone)
        pill_bg = REPORT_COLORS.get(f"pill_{pill_tone}_bg", REPORT_COLORS["pill_low_bg"])
        pill_text = REPORT_COLORS.get(f"pill_{pill_tone}_text", REPORT_COLORS["pill_low_text"])
        title_html += (
            f'  <font size="7" color="{pill_text}">'
            f'<span backColor="{pill_bg}"> {escape(badge)} </span></font>'
        )
    rows: list[list[object]] = [[Paragraph(title_html, style_note)]]
    for flowable in body_flowables:
        rows.append([flowable])
    card = Table(rows, colWidths=[None])
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(tone_bg)),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(tone_border)),
                ("LEFTPADDING", (0, 0), (-1, -1), CARD_PADDING),
                ("RIGHTPADDING", (0, 0), (-1, -1), CARD_PADDING),
                ("TOPPADDING", (0, 0), (-1, -1), CARD_PADDING),
                ("BOTTOMPADDING", (0, 0), (-1, -1), CARD_PADDING),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROUNDEDCORNERS", [CARD_RADIUS, CARD_RADIUS, CARD_RADIUS, CARD_RADIUS]),
            ]
        )
    )
    return card


def compact_note_panel(
    title: str,
    note: str,
    width: float,
    *,
    style_note: Any,
    height: float = 170,
) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    panel = Table(
        [
            [Paragraph(f"<b>{escape(title)}</b>", style_note)],
            [Spacer(1, 6)],
            [Paragraph(escape(note), style_note)],
        ],
        colWidths=[width],
        rowHeights=[16, 8, height - 24],
    )
    panel.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(REPORT_COLORS["surface"])),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor(REPORT_COLORS["card_neutral_border"]),
                ),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROUNDEDCORNERS", [CARD_RADIUS, CARD_RADIUS, CARD_RADIUS, CARD_RADIUS]),
            ]
        )
    )
    return panel
