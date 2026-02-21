"""PDF report helper functions – color utilities and location hotspot analysis."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import TYPE_CHECKING

from ..report_theme import (
    FINDING_SOURCE_COLORS,
)
from ..runlog import as_float_or_none as _as_float

if TYPE_CHECKING:
    from collections.abc import Callable


# ── Pure helpers (no external deps) ──────────────────────────────────────


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


# ── Location hotspot analysis ─────────────────────────────────────────


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
