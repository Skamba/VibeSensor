"""Report view model: every string and number the PDF draws, built from one stored run.

Pure translation of the persisted analysis (``AnalysisSummary``, whose
``diagnosis`` block carries the verdict) plus the run metadata into localized
text. It never re-derives the verdict, levels, order labels, amplitudes, or
zones; the renderer in ``report/pdf.py`` only lays this out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor._version import __version__
from vibesensor.common.time_utils import format_run_timestamp
from vibesensor.domain.locations import location_code_for_label
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.report.i18n import normalize_lang, resolve_i18n, tr
from vibesensor.report.run_quality import (
    suitability_check_detail,
    warning_codes_stated_by_checks,
)
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.diagnosis_contracts import (
    DiagnosisPayload,
    LocationAmplitudeRow,
    OrderFindingRow,
    ReferenceProvenanceValue,
    TestConditions,
)
from vibesensor.summary.phases import PHASE_I18N_KEYS

__all__ = [
    "AmplitudeRow",
    "CarDiagram",
    "DiagramMarker",
    "Fact",
    "MechanicPage",
    "OwnerPage",
    "QualityCheck",
    "QualitySection",
    "ReportView",
    "SpectrumChart",
    "SpeedChart",
    "SpeedSeries",
    "WorksheetRow",
    "build_report_view",
]

_NBSP = "\u00a0"
_SPEED_SWEEP_MIN_KMH = 30.0
_DOMINANT_RATIO = 1.5
_MAX_SPEED_SERIES = 4
_MAX_AMPLITUDE_ROWS = 8  # strongest first; keeps the workshop page on one sheet
_SOURCE_KEYS = {"wheel/tire": "WHEEL", "driveline": "DRIVELINE", "engine": "ENGINE"}
_ZONE_KEYS = frozenset(
    {
        "front_left_wheel",
        "front_right_wheel",
        "rear_left_wheel",
        "rear_right_wheel",
        "front_axle",
        "rear_axle",
        "all_wheels",
        "engine_bay",
        "driveshaft_tunnel",
        "transmission",
    }
)
_WHEEL_CORNERS = frozenset(
    {"front_left_wheel", "front_right_wheel", "rear_left_wheel", "rear_right_wheel"}
)
_WHEEL_ZONES = _WHEEL_CORNERS | {"front_axle", "rear_axle", "all_wheels"}
_WEAK_REASON_KEYS = {
    "spread_across_locations": "WEAK_SPREAD",
    "narrow_speed_range": "WEAK_NARROW_SPEED",
    "intermittent": "WEAK_INTERMITTENT",
    "faint": "WEAK_FAINT",
    "single_sensor": "WEAK_SINGLE_SENSOR",
    "coast_test_contradicts": "WEAK_COAST_CONTRADICTS",
    "manual_speed": "WEAK_MANUAL_SPEED",
}
_SPEED_DEPENDENCE_KEYS = {
    "vehicle_speed": "SPEED_DEPENDENCE_VEHICLE",
    "engine_speed": "SPEED_DEPENDENCE_ENGINE",
}
_SPEED_SOURCE_KEYS = {
    "gps": "SPEED_SOURCE_GPS",
    "obd2": "SPEED_SOURCE_OBD",
    "manual": "SPEED_SOURCE_MANUAL",
    "fallback_manual": "SPEED_SOURCE_FALLBACK_MANUAL",
}
_RECAPTURE_KEYS = ("RECAPTURE_ROAD", "RECAPTURE_SWEEP", "RECAPTURE_HOLD", "RECAPTURE_COAST")
# An EV cannot coast in neutral: its motor stays coupled to the wheels.
_RECAPTURE_KEYS_EV = ("RECAPTURE_ROAD", "RECAPTURE_SWEEP", "RECAPTURE_HOLD")
# An EV's motor turns at the driveshaft order (wheel speed x reduction ratio), so
# the driveline family reads as the motor and P1/P2 as motor revolutions.
_EV_ORDER_CODES = frozenset({"P1", "P2"})
_RPM_KEYS = {
    "measured": "RPM_MEASURED",
    "estimated_top_gear": "RPM_ESTIMATED_TOP_GEAR",
    "none": "RPM_NONE",
}
_SHOP_KEYS = {
    "WHEEL": ("SHOP_TIRE_ROAD_FORCE", "SHOP_TIRE_MATCH", "SHOP_TIRE_RUNOUT"),
    "DRIVELINE": ("SHOP_DRIVELINE_RUNOUT", "SHOP_DRIVELINE_ANGLES", "SHOP_DRIVELINE_ORDERS"),
    "ENGINE": ("SHOP_ENGINE_MOUNTS", "SHOP_ENGINE_ORDERS", "SHOP_ENGINE_MISFIRE"),
    "MOTOR": ("SHOP_MOTOR_MOUNTS", "SHOP_MOTOR_BALANCE", "SHOP_MOTOR_ORDERS"),
}
_RULED_OUT_KEYS = {
    "WHEEL": "RULED_OUT_WHEEL",
    "DRIVELINE": "RULED_OUT_DRIVELINE",
    "ENGINE": "RULED_OUT_ENGINE",
    "MOTOR": "RULED_OUT_MOTOR",
}
_NOT_TESTABLE_KEYS = {
    "no_tire_reference": "NOT_TESTABLE_TIRE",
    "no_drive_reference": "NOT_TESTABLE_DRIVE",
    "no_engine_reference": "NOT_TESTABLE_ENGINE",
    "manual_speed": "NOT_TESTABLE_MANUAL_SPEED",
    "engine_not_running": "NOT_TESTABLE_ENGINE_NOT_RUNNING",
}
_RULED_OUT_ESTIMATED_KEYS = {
    "estimated_final_drive": "RULED_OUT_ESTIMATED_FINAL_DRIVE",
    "estimated_top_gear": "RULED_OUT_ESTIMATED_TOP_GEAR",
    "top_gear_assumed": "RULED_OUT_ENGINE_TOP_GEAR",
    "engine_may_be_off": "RULED_OUT_ENGINE_MAY_BE_OFF",
}
# Page 1 of a no-fault run: what each untested or estimate-based check leaves open,
# and how to close it; the short hedge names the estimate in the "checked" list.
_COULDNT_TEST_KEYS = {
    "no_tire_reference": "COULDNT_TEST_TIRE",
    "no_drive_reference": "COULDNT_TEST_DRIVE",
    "no_engine_reference": "COULDNT_TEST_ENGINE",
    "manual_speed": "COULDNT_TEST_MANUAL_SPEED",
    "engine_not_running": "COULDNT_TEST_ENGINE_NOT_RUNNING",
}
_CHECKED_LIMITED_KEYS = {
    "estimated_final_drive": "CHECKED_LIMITED_FINAL_DRIVE",
    "estimated_top_gear": "CHECKED_LIMITED_TOP_GEAR",
    "top_gear_assumed": "CHECKED_LIMITED_ENGINE_TOP_GEAR",
    "engine_may_be_off": "CHECKED_LIMITED_ENGINE_MAY_BE_OFF",
}
_CHECKED_HEDGE_KEYS = {
    "estimated_final_drive": "CHECKED_HEDGE_FINAL_DRIVE",
    "estimated_top_gear": "CHECKED_HEDGE_TOP_GEAR",
    "top_gear_assumed": "CHECKED_HEDGE_ENGINE_TOP_GEAR",
    "engine_may_be_off": "CHECKED_HEDGE_ENGINE_MAY_BE_OFF",
}
# The engine's own wording: measured RPM tests it without the tire size or ratios, and
# an estimated RPM always assumes top gear.
_ENGINE_CHECK_KEYS = {
    "COULDNT_TEST_TIRE": "COULDNT_TEST_ENGINE_TIRE",
    "COULDNT_TEST_DRIVE": "COULDNT_TEST_ENGINE_DRIVE",
    "CHECKED_HEDGE_FINAL_DRIVE": "CHECKED_HEDGE_ENGINE_FINAL_DRIVE",
    "CHECKED_LIMITED_FINAL_DRIVE": "CHECKED_LIMITED_ENGINE_FINAL_DRIVE",
}


# -- view types ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fact:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class DiagramMarker:
    """One sensor on the car diagram; ``ratio`` 1.0 is the strongest location."""

    code: str
    label: str
    value: str
    ratio: float | None
    strongest: bool


@dataclass(frozen=True, slots=True)
class CarDiagram:
    zone: str | None
    markers: tuple[DiagramMarker, ...]
    front_label: str


@dataclass(frozen=True, slots=True)
class OwnerPage:
    """Page 1: verdict, one confidence level, plain description, what to do."""

    verdict: str
    headline: str
    level: str | None
    confidence_label: str
    level_word: str | None
    level_meaning: str | None
    description: str
    candidate: str | None
    reasons_title: str | None
    reasons: tuple[str, ...]
    covered_title: str | None
    covered: str | None
    not_covered_title: str | None
    not_covered: tuple[str, ...]
    next_step_title: str
    confirm_title: str | None
    confirm: str | None
    next_step: str
    fallback_step: str | None
    recapture_title: str | None
    recapture: tuple[str, ...]
    verify_title: str | None
    verify: str | None
    diagram: CarDiagram


@dataclass(frozen=True, slots=True)
class WorksheetRow:
    order: str
    frequency: str
    speeds: str
    phases: str
    present: str
    location: str
    level: str
    diagnosed: bool


@dataclass(frozen=True, slots=True)
class AmplitudeRow:
    location: str
    amplitude: str
    ratio: str
    strongest: bool


@dataclass(frozen=True, slots=True)
class SpectrumChart:
    title: str
    floor_label: str
    floor_mg: float | None
    peaks: tuple[tuple[float, float], ...]
    markers: tuple[tuple[str, float], ...]
    highlight: str | None
    x_max_hz: float


@dataclass(frozen=True, slots=True)
class SpeedSeries:
    label: str
    points: tuple[tuple[float, float], ...]
    strongest: bool


@dataclass(frozen=True, slots=True)
class SpeedChart:
    title: str
    series: tuple[SpeedSeries, ...]


@dataclass(frozen=True, slots=True)
class MechanicPage:
    """Page 2: conditions, worksheet, per-location amplitudes, charts, ruled out, shop request."""

    title: str
    conditions_title: str
    conditions: tuple[Fact, ...]
    worksheet_title: str
    worksheet_header: tuple[str, ...]
    worksheet: tuple[WorksheetRow, ...]
    worksheet_empty: str | None
    amplitude_title: str
    amplitude_header: tuple[str, str, str]
    amplitudes: tuple[AmplitudeRow, ...]
    spectrum: SpectrumChart | None
    speed_chart: SpeedChart | None
    ruled_out_title: str
    ruled_out: tuple[str, ...]
    shop_title: str
    shop: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QualityCheck:
    label: str
    state: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class QualitySection:
    """Data quality and traceability; one footer line when every check passed."""

    title: str
    all_passed: bool
    footer_line: str
    header: tuple[str, str, str]
    checks: tuple[QualityCheck, ...]
    warnings: tuple[str, ...]
    traceability: tuple[Fact, ...]


@dataclass(frozen=True, slots=True)
class ReportView:
    lang: str
    title: str
    header: tuple[Fact, ...]
    owner: OwnerPage
    mechanic: MechanicPage
    quality: QualitySection

    def page_label(self, page: int, total: int) -> str:
        return tr(self.lang, "PAGE_OF", page=page, total=total)


# -- entry point -----------------------------------------------------------------


def build_report_view(
    analysis: AnalysisSummary,
    metadata: RunMetadata,
    *,
    lang: str | None = None,
    time_zone: str | None = None,
) -> ReportView:
    """Build the full report view for one stored run in ``lang`` (default: the run's).

    Times show in IANA ``time_zone`` (the user's) when given, else in the offset
    recorded with the run.
    """
    diagnosis = analysis["diagnosis"]
    ctx = _Ctx(
        normalize_lang(lang or analysis.get("lang") or metadata.language),
        electric=diagnosis["conditions"]["fuel_type"] == "EV",
    )
    return ReportView(
        lang=ctx.lang,
        title=ctx.t("REPORT_TITLE"),
        header=_header(ctx, analysis, metadata, time_zone),
        owner=_owner_page(ctx, analysis, diagnosis),
        mechanic=_mechanic_page(ctx, analysis, metadata, diagnosis),
        quality=_quality(ctx, analysis, metadata),
    )


# -- formatting ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ctx:
    lang: str
    # A battery-electric car: "motor" wording, no engine, no neutral coast-down.
    electric: bool = False

    def t(self, key: str, **kwargs: object) -> str:
        return tr(self.lang, key, **{k: _text(v) for k, v in kwargs.items()})

    def t_or(self, key: str, fallback: str) -> str:
        text = self.t(key)
        return fallback if text == key else text

    def num(self, value: float, digits: int = 0) -> str:
        text = f"{value:.{digits}f}"
        return text.replace(".", ",") if self.lang == "nl" else text

    def hz(self, value: float) -> str:
        return f"{self.num(value, 1)}{_NBSP}Hz"

    def mg(self, value: float) -> str:
        return f"{self.num(value, 1 if value < 10 else 0)}{_NBSP}mg"

    def kmh(self, value: float) -> str:
        return f"{self.num(value)}{_NBSP}km/h"

    def share(self, ratio: float) -> str:
        return f"{self.num(100.0 * ratio)}{_NBSP}%"

    def ratio(self, ratio: float) -> str:
        if ratio >= 10:
            return f"{self.num(ratio)}x"
        if ratio >= 0.1:
            return f"{self.num(ratio, 1)}x"
        return f"{self.num(ratio, 3 if ratio < 0.01 else 2)}x"

    def location(self, label: str | None) -> str:
        if not label:
            return self.t("VALUE_UNKNOWN")
        code = location_code_for_label(label)
        return self.t(f"LOC_{code.upper()}") if code else label

    def zone(self, diagnosis: DiagnosisPayload) -> str:
        """Noun phrase for where to look (``the front-left wheel``, ``the engine bay``)."""
        zone = diagnosis["zone"]
        if diagnosis["source"] == "wheel/tire" and zone in {"front_axle", "rear_axle"}:
            return self.t(f"WHEELS_{zone.upper()}")
        if self.electric and zone == "driveshaft_tunnel":
            # An EV has no propshaft: a motor order no axle dominates is the drive unit.
            return self.t("ZONE_DRIVE_UNIT_EV")
        if zone in _ZONE_KEYS:
            return self.t(f"ZONE_{zone.upper()}")
        if zone:
            # Another mounting point (a seat, the boot): the location it names.
            return self.t_or(f"LOC_{zone.upper()}", self.location(diagnosis["location"]))
        return self.location(diagnosis["location"])

    def source_key(self, source: str | None) -> str | None:
        """Catalog stem of a source family; an EV's driveline order is its motor."""
        key = _SOURCE_KEYS.get(source or "")
        return "MOTOR" if self.electric and key == "DRIVELINE" else key

    def order_key(self, code: str) -> str:
        """Catalog key of an order code's plain wording (P1/P2 turn the motor on an EV)."""
        return f"ORDER_{code}_EV" if self.electric and code in _EV_ORDER_CODES else f"ORDER_{code}"

    def phase(self, phase: str) -> str:
        key = PHASE_I18N_KEYS.get(phase)
        return self.t(key) if key else phase.replace("_", " ")

    def join(self, items: list[str]) -> str:
        """``a, b and c`` in the report language."""
        if len(items) < 2:
            return "".join(items)
        return self.t("LIST_AND", items=", ".join(items[:-1]), last=items[-1])

    def speed_range(self, low: float | None, high: float | None) -> str:
        if low is None or high is None:
            return self.t("VALUE_UNKNOWN")
        low_text, high_text = self.num(low), self.num(high)
        # A steady run reads "50 km/h", not "50–50 km/h".
        value = low_text if low_text == high_text else f"{low_text}–{high_text}"
        return f"{value}{_NBSP}km/h"


def _text(value: object) -> str:
    return value if isinstance(value, str) else str(value)


# -- header ----------------------------------------------------------------------


def _duration(seconds: float) -> str:
    total = max(0, round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _tire_size(metadata: RunMetadata) -> str | None:
    settings = metadata.analysis_settings
    if settings.tire_width_mm <= 0 or settings.tire_aspect_pct <= 0 or settings.rim_in <= 0:
        return None
    return f"{settings.tire_width_mm:g}/{settings.tire_aspect_pct:g}R{settings.rim_in:g}"


def _car_name(ctx: _Ctx, metadata: RunMetadata) -> str:
    name = (metadata.car_name or "").strip()
    car_type = (metadata.car_type or "").strip()
    if name and car_type:
        return f"{name} ({car_type})"
    return name or car_type or ctx.t("VALUE_UNKNOWN")


def _header(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    metadata: RunMetadata,
    time_zone: str | None,
) -> tuple[Fact, ...]:
    speeds = analysis["speed_stats"]
    unknown = ctx.t("VALUE_UNKNOWN")
    return (
        Fact(ctx.t("HEADER_CAR"), _car_name(ctx, metadata)),
        Fact(ctx.t("HEADER_TIRES"), _tire_size(metadata) or unknown),
        Fact(
            ctx.t("HEADER_DATE"),
            format_run_timestamp(
                analysis.get("start_time_utc") or metadata.start_time_utc,
                time_zone=time_zone,
                recorded_utc_offset_seconds=metadata.recorded_utc_offset_seconds,
            )
            or unknown,
        ),
        Fact(ctx.t("HEADER_SPEEDS"), ctx.speed_range(speeds["min_kmh"], speeds["max_kmh"])),
        Fact(ctx.t("HEADER_DURATION"), _duration(analysis["duration_s"])),
        Fact(ctx.t("HEADER_SENSORS"), str(analysis["sensor_count_used"])),
    )


# -- page 1 ----------------------------------------------------------------------


def _owner_page(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    diagnosis: DiagnosisPayload,
) -> OwnerPage:
    verdict = diagnosis["verdict"]
    level = diagnosis["confidence_level"]
    zone = ctx.zone(diagnosis)
    headline = ctx.t("VERDICT_NO_FAULT")
    description = ""
    candidate = reasons_title = covered = confirm = None
    fallback_step = verify = None
    level_meaning = ctx.t(f"LEVEL_{level.upper()}_MEANING") if level else None
    reasons: tuple[str, ...] = ()
    recapture: tuple[str, ...] = ()
    not_covered: tuple[str, ...] = ()
    next_step = ctx.t("STEP_NO_FAULT")
    if verdict == "no_fault":
        description, covered, not_covered = _coverage(ctx, analysis, diagnosis)
    elif verdict == "weak_evidence":
        headline = ctx.t("VERDICT_WEAK")
        description = _description(ctx, diagnosis)
        candidate = ctx.t("VERDICT_WEAK_CANDIDATE", cause=_cause(ctx, diagnosis))
        reasons = tuple(_weak_reason(ctx, reason) for reason in diagnosis["weak_reasons"])
        reasons_title = ctx.t("WEAK_REASONS_TITLE") if reasons else None
        recapture = tuple(
            ctx.t(key) for key in (_RECAPTURE_KEYS_EV if ctx.electric else _RECAPTURE_KEYS)
        )
        if _unlocated_wheel(diagnosis):
            recapture = (ctx.t("STEP_WHEEL_UNLOCATED"), *recapture)
        next_step = ctx.t("RECAPTURE_TITLE")
    else:
        step_key = _step_key(ctx, diagnosis)
        headline = ctx.t("VERDICT_LIKELY_CAUSE", cause=_cause(ctx, diagnosis))
        description = _description(ctx, diagnosis)
        if level == "moderate":
            confirm = _confirm_check(ctx, diagnosis)
            if confirm is None:
                level_meaning = ctx.t("LEVEL_MODERATE_COAST_DONE_MEANING")
        if _unlocated_wheel(diagnosis):
            # Locating the wheel comes first; the shop route is the alternative.
            next_step = ctx.t("STEP_WHEEL_UNLOCATED")
            fallback_step = ctx.t("STEP_WHEEL_UNLOCATED_ALTERNATIVE")
        else:
            next_step = ctx.t(step_key, zone=zone)
            fallback_step = ctx.t("FALLBACK_PREFIX", step=ctx.t(f"{step_key}_FALLBACK", zone=zone))
        verify = _verify(ctx, diagnosis)
    return OwnerPage(
        verdict=verdict,
        headline=headline,
        confidence_label=ctx.t("CONFIDENCE"),
        level=level,
        level_word=ctx.t(f"LEVEL_{level.upper()}") if level else None,
        level_meaning=level_meaning,
        description=description,
        candidate=candidate,
        reasons_title=reasons_title,
        reasons=reasons,
        covered_title=ctx.t("COVERED") if covered else None,
        covered=covered,
        not_covered_title=ctx.t("NOT_COVERED") if not_covered else None,
        not_covered=not_covered,
        next_step_title=ctx.t("NEXT_STEP"),
        confirm_title=ctx.t("CONFIRM_FIRST") if confirm else None,
        confirm=confirm,
        next_step=next_step,
        fallback_step=fallback_step,
        recapture_title=ctx.t("RECAPTURE_TITLE") if recapture else None,
        recapture=recapture,
        verify_title=ctx.t("VERIFY_TITLE") if verify else None,
        verify=verify,
        diagram=_diagram(ctx, diagnosis),
    )


def _unlocated_wheel(diagnosis: DiagnosisPayload) -> bool:
    """A wheel/tire fault felt strongest away from the wheels (no wheel sensor near it)."""
    return diagnosis["source"] == "wheel/tire" and diagnosis["zone"] not in _WHEEL_ZONES


def _cause(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    if _unlocated_wheel(diagnosis):
        return ctx.t("CAUSE_WHEEL_UNLOCATED", zone=ctx.zone(diagnosis))
    key = ctx.source_key(diagnosis["source"]) or "OTHER"
    return ctx.t(f"CAUSE_{key}", zone=ctx.zone(diagnosis))


def _step_key(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    code = diagnosis["order_code"]
    if not code:
        return "STEP_OTHER"
    return f"STEP_{code}_EV" if ctx.electric and code in _EV_ORDER_CODES else f"STEP_{code}"


def _confirm_check(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    """The cheap check for a Moderate fault; ``None`` when the guided coast-down already did it."""
    if diagnosis["source"] == "wheel/tire":
        if diagnosis["zone"] in _WHEEL_CORNERS:
            return ctx.t("CONFIRM_WHEEL", zone=ctx.zone(diagnosis))
        if diagnosis["zone"] != "all_wheels":
            return ctx.t("CONFIRM_AXLE")
        # On all four wheels a swap moves nothing; the coast-down still tells it from the engine.
    if ctx.electric:
        # No neutral decouples an EV's motor: a repeat of the same drive is the check.
        return ctx.t("CONFIRM_REPEAT_EV")
    if diagnosis["speed_dependence"] is not None:
        return None
    return ctx.t("CONFIRM_NEUTRAL")


def _strongest_two(diagnosis: DiagnosisPayload) -> list[LocationAmplitudeRow]:
    return [row for row in diagnosis["location_amplitudes"] if row["amplitude_mg"] is not None][:2]


def _description(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    """One plain sentence: what repeats, at which frequency, where, and over which speeds."""
    code = diagnosis["order_code"]
    hz = diagnosis["frequency_hz"]
    speed = diagnosis["reference_speed_kmh"]
    if code and hz is not None and speed is not None:
        order = ctx.t(ctx.order_key(code))
        if code == "E2":
            order = f"{order} ({ctx.t('ORDER_E2_NOTE')})"
        parts = [ctx.t("DESC_ORDER", order=order, hz=ctx.hz(hz), speed=ctx.kmh(speed))]
    elif hz is not None:
        parts = [ctx.t("DESC_FREQUENCY", hz=ctx.hz(hz))]
    else:
        parts = []
    top = _strongest_two(diagnosis)
    if top:
        location = ctx.location(top[0]["location"])
        if len(top) == 2 and top[1]["ratio_to_strongest"]:
            ratio = 1.0 / top[1]["ratio_to_strongest"]
            if ratio >= _DOMINANT_RATIO:
                parts.append(ctx.t("DESC_STRONGER", ratio=ctx.ratio(ratio), location=location))
            else:
                other = ctx.location(top[1]["location"])
                parts.append(ctx.t("DESC_SIMILAR", location=location, other=other))
        else:
            parts.append(ctx.t("DESC_STRONGEST_AT", location=location))
    low, high = diagnosis["speed_min_kmh"], diagnosis["speed_max_kmh"]
    if low is not None and high is not None:
        if high - low >= 10.0:
            parts.append(ctx.t("DESC_PRESENT_RANGE", low=ctx.num(low), high=ctx.num(high)))
        else:
            parts.append(ctx.t("DESC_PRESENT_AT", speeds=ctx.speed_range(low, high)))
    sentence = ", ".join(parts)
    text = f"{sentence[:1].upper()}{sentence[1:]}." if sentence else ""
    dependence = diagnosis["speed_dependence"]
    if dependence is not None:
        text = f"{text} {ctx.t(_SPEED_DEPENDENCE_KEYS[dependence])}".strip()
    return text


def _weak_reason(ctx: _Ctx, reason: str) -> str:
    key = _WEAK_REASON_KEYS.get(reason)
    return ctx.t(key) if key is not None else reason


def _verify(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    text = ctx.t("VERIFY_BODY")
    top = _strongest_two(diagnosis)
    if diagnosis["amplitude_basis"] == "order" and top and top[0]["amplitude_mg"] is not None:
        level = ctx.t(
            "VERIFY_LEVEL",
            location=ctx.location(top[0]["location"]),
            amplitude=f"{diagnosis['order_code'] or ''} {ctx.mg(top[0]['amplitude_mg'])}".strip(),
        )
        text = f"{text} {level}"
    return text


def _check_text(ctx: _Ctx, table: Mapping[str, str], source_key: str, reason: str) -> str:
    key = table[reason]
    if source_key == "ENGINE":
        key = _ENGINE_CHECK_KEYS.get(key, key)
    return ctx.t(key)


def _coverage(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    diagnosis: DiagnosisPayload,
) -> tuple[str, str, tuple[str, ...]]:
    """A no-fault run's verdict sentence, what it covered, and what it did not.

    The sentence names only the sources this run could check (hedged when the
    check rests on an estimate) and says which it could not; "Not covered" gives
    each untested or estimate-based source with how to close the gap, then the
    speeds and driving the run left out.
    """
    checked: list[str] = []
    not_checked: list[str] = []
    gaps: list[str] = []
    for check in diagnosis["source_checks"]:
        key = ctx.source_key(check["source"])
        # A source the car does not have (an EV's engine) is neither checked nor a gap.
        if key is None or check["status"] == "not_applicable":
            continue
        name = ctx.t(f"SOURCE_{key}_NOUN")
        reason = check["reason"] or ""
        if check["status"] == "not_testable":
            not_checked.append(name)
            detail = _check_text(ctx, _COULDNT_TEST_KEYS, key, reason)
        elif check["status"] == "ruled_out_estimated":
            hedge = _check_text(ctx, _CHECKED_HEDGE_KEYS, key, reason)
            checked.append(ctx.t("CHECKED_HEDGED", source=name, hedge=hedge))
            detail = _check_text(ctx, _CHECKED_LIMITED_KEYS, key, reason)
        else:
            checked.append(name)
            continue
        gaps.append(ctx.t("NOT_COVERED_SOURCE", source=ctx.t(f"SOURCE_{key}"), detail=detail))
    description = (
        ctx.t("VERDICT_NO_FAULT_BODY", checked=ctx.join(checked))
        if checked
        else ctx.t(
            "VERDICT_NO_FAULT_BODY_NOTHING_CHECKED_EV"
            if ctx.electric
            else "VERDICT_NO_FAULT_BODY_NOTHING_CHECKED"
        )
    )
    if not_checked and checked:
        description = (
            f"{description} {ctx.t('VERDICT_NO_FAULT_NOT_CHECKED', sources=ctx.join(not_checked))}"
        )

    speeds = analysis["speed_stats"]
    phases = analysis["phase_info"]["phase_pcts"]
    driven = [phase for phase, share in phases.items() if share >= 1.0 and phase != "speed_unknown"]
    locations = [ctx.location(row["location"]) for row in diagnosis["location_amplitudes"]]
    covered = ctx.t(
        "COVERED_BODY",
        speeds=ctx.speed_range(speeds["min_kmh"], speeds["max_kmh"]),
        phases=", ".join(ctx.phase(phase) for phase in driven) or ctx.t("VALUE_UNKNOWN"),
        locations=", ".join(locations) or ctx.t("VALUE_UNKNOWN"),
    )
    low, high = speeds["min_kmh"], speeds["max_kmh"]
    if low is not None and low > 30.0:
        gaps.append(ctx.t("NOT_COVERED_BELOW", speed=ctx.num(low)))
    if high is not None and high < 120.0:
        gaps.append(ctx.t("NOT_COVERED_ABOVE", speed=ctx.num(high)))
    if "cruise" not in driven:
        gaps.append(ctx.t("NOT_COVERED_CRUISE"))
    if not {"deceleration", "coast_down"} & set(driven):
        gaps.append(ctx.t("NOT_COVERED_COAST"))
    return description, covered, tuple(f"{gap[:1].upper()}{gap[1:]}" for gap in gaps)


def _diagram(ctx: _Ctx, diagnosis: DiagnosisPayload) -> CarDiagram:
    markers: list[DiagramMarker] = []
    for index, row in enumerate(diagnosis["location_amplitudes"]):
        code = location_code_for_label(row["location"])
        if code is None:
            continue
        amplitude = row["amplitude_mg"]
        markers.append(
            DiagramMarker(
                code=code,
                label=ctx.location(row["location"]),
                value=ctx.mg(amplitude) if amplitude is not None else "-",
                ratio=row["ratio_to_strongest"],
                strongest=index == 0 and amplitude is not None,
            )
        )
    return CarDiagram(
        zone=diagnosis["zone"] if diagnosis["verdict"] != "no_fault" else None,
        markers=tuple(markers),
        front_label=ctx.t("DIAGRAM_FRONT"),
    )


# -- page 2 ----------------------------------------------------------------------


def _mechanic_page(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    metadata: RunMetadata,
    diagnosis: DiagnosisPayload,
) -> MechanicPage:
    order_code = diagnosis["order_code"]
    return MechanicPage(
        title=ctx.t("PAGE2_TITLE"),
        conditions_title=ctx.t("CONDITIONS_TITLE"),
        conditions=_conditions(ctx, analysis, metadata, diagnosis),
        worksheet_title=ctx.t("WORKSHEET_TITLE"),
        worksheet_header=tuple(
            ctx.t(key)
            for key in (
                "WS_ORDER",
                "WS_FREQUENCY",
                "WS_SPEEDS",
                "WS_PHASES",
                "WS_PRESENT",
                "WS_LOCATION",
                "WS_LEVEL",
            )
        ),
        worksheet=tuple(
            _worksheet_row(ctx, row, diagnosed=row["finding_id"] == diagnosis["finding_id"])
            for row in diagnosis["order_findings"]
        ),
        worksheet_empty=_worksheet_empty(ctx, diagnosis),
        amplitude_title=(
            ctx.t("AMPLITUDE_TITLE_ORDER", order=order_code)
            if diagnosis["amplitude_basis"] == "order" and order_code
            else ctx.t("AMPLITUDE_TITLE_OVERALL")
        ),
        amplitude_header=(ctx.t("AMP_LOCATION"), ctx.t("AMP_LEVEL"), ctx.t("AMP_RATIO")),
        amplitudes=tuple(
            _amplitude_row(ctx, row)
            for row in diagnosis["location_amplitudes"][:_MAX_AMPLITUDE_ROWS]
        ),
        spectrum=_spectrum(ctx, diagnosis),
        speed_chart=_speed_chart(ctx, diagnosis),
        ruled_out_title=ctx.t("RULED_OUT_TITLE"),
        ruled_out=_ruled_out(ctx, diagnosis),
        shop_title=ctx.t("SHOP_TITLE"),
        shop=_shop(ctx, diagnosis),
    )


def _conditions(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    metadata: RunMetadata,
    diagnosis: DiagnosisPayload,
) -> tuple[Fact, ...]:
    conditions = diagnosis["conditions"]
    unknown = ctx.t("VALUE_UNKNOWN")
    circumference = conditions["tire_circumference_m"]
    tire = _tire_size(metadata)
    if circumference is not None:
        around = ctx.t("COND_CIRCUMFERENCE", circumference=ctx.num(circumference, 3))
        tire = f"{tire}, {around}" if tire else around
    final_drive, gear = conditions["final_drive_ratio"], conditions["gear_ratio"]
    source = conditions["speed_source"]
    speed_key = _SPEED_SOURCE_KEYS.get(source or "")
    speed_source = ctx.t(speed_key) if speed_key else unknown
    phases = ", ".join(
        ctx.t("PHASE_SHARE", phase=ctx.phase(phase), share=ctx.share(share / 100.0))
        for phase, share in sorted(
            analysis["phase_info"]["phase_pcts"].items(), key=lambda item: -item[1]
        )
        if share >= 1.0
    )
    sensors = ", ".join(ctx.location(location) for location in analysis["sensor_locations"])
    speeds = analysis["speed_stats"]
    references = [
        Fact(ctx.t("COND_POWERTRAIN"), ctx.t(_powertrain_key(conditions))),
        Fact(ctx.t("COND_TIRE"), _with_provenance(ctx, tire, conditions["tire_provenance"])),
        Fact(
            ctx.t("COND_FINAL_DRIVE_EV" if ctx.electric else "COND_FINAL_DRIVE"),
            _with_provenance(
                ctx,
                ctx.num(final_drive, 2) if final_drive is not None else None,
                conditions["final_drive_provenance"],
            ),
        ),
    ]
    # An EV has one fixed reduction and no engine: no top gear and no engine RPM.
    if not ctx.electric:
        references.append(
            Fact(
                ctx.t("COND_TOP_GEAR"),
                _with_provenance(
                    ctx,
                    ctx.num(gear, 2) if gear is not None else None,
                    conditions["gear_ratio_provenance"],
                ),
            )
        )
    references.append(Fact(ctx.t("COND_SPEED_SOURCE"), speed_source))
    if not ctx.electric:
        references.append(Fact(ctx.t("COND_RPM"), ctx.t(_RPM_KEYS[conditions["rpm_source"]])))
    return (
        *references,
        Fact(ctx.t("HEADER_SPEEDS"), ctx.speed_range(speeds["min_kmh"], speeds["max_kmh"])),
        Fact(ctx.t("COND_PHASES"), phases or unknown),
        Fact(
            ctx.t("COND_GUIDED"),
            ", ".join(ctx.t(f"GUIDED_{phase.upper()}") for phase in diagnosis["guided_phases"])
            or ctx.t("GUIDED_NONE"),
        ),
        Fact(ctx.t("COND_SENSORS"), sensors or unknown),
    )


def _powertrain_key(conditions: TestConditions) -> str:
    """The car's powertrain with what it means for the checks (PHEV: was the engine on?)."""
    fuel_type = conditions["fuel_type"]
    if fuel_type == "PHEV":
        measured = conditions["rpm_source"] == "measured"
        return "POWERTRAIN_PHEV_MEASURED" if measured else "POWERTRAIN_PHEV_ESTIMATED"
    return {"EV": "POWERTRAIN_EV", "ICE": "POWERTRAIN_ICE"}.get(
        fuel_type or "", "POWERTRAIN_UNKNOWN"
    )


def _with_provenance(ctx: _Ctx, value: str | None, provenance: ReferenceProvenanceValue) -> str:
    """A car reference with where it came from; a missing one says it was not provided."""
    if value is None or provenance == "missing":
        return ctx.t("PROVENANCE_MISSING")
    return ctx.t(
        "COND_WITH_PROVENANCE", value=value, provenance=ctx.t(f"PROVENANCE_{provenance.upper()}")
    )


def _worksheet_row(ctx: _Ctx, row: OrderFindingRow, *, diagnosed: bool) -> WorksheetRow:
    code = row["order_code"]
    hz, speed = row["frequency_hz"], row["reference_speed_kmh"]
    presence = row["presence_ratio"]
    return WorksheetRow(
        order=f"{code} - {ctx.t(ctx.order_key(code))}",
        frequency=(
            f"{ctx.hz(hz)} @ {ctx.kmh(speed)}"
            if hz is not None and speed is not None
            else ctx.t("VALUE_UNKNOWN")
        ),
        speeds=ctx.speed_range(row["speed_min_kmh"], row["speed_max_kmh"]),
        phases=", ".join(ctx.phase(phase) for phase in row["phases"]) or "-",
        present=ctx.share(presence) if presence is not None else "-",
        location=ctx.location(row["location"]),
        level=ctx.t(f"LEVEL_{row['confidence_level'].upper()}"),
        diagnosed=diagnosed,
    )


def _worksheet_empty(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    if diagnosis["order_findings"]:
        return None
    if diagnosis["verdict"] != "no_fault" and diagnosis["frequency_hz"] is not None:
        return ctx.t("WS_PEAK_ONLY", hz=ctx.hz(diagnosis["frequency_hz"]))
    return ctx.t("WS_NONE_EV" if ctx.electric else "WS_NONE")


def _amplitude_row(ctx: _Ctx, row: LocationAmplitudeRow) -> AmplitudeRow:
    amplitude, db, ratio = row["amplitude_mg"], row["db_above_floor"], row["ratio_to_strongest"]
    if amplitude is None:
        text = ctx.t("AMP_NOT_DETECTED")
    elif db is not None:
        text = f"{ctx.mg(amplitude)} ({ctx.num(db)} dB)"
    else:
        text = ctx.mg(amplitude)
    return AmplitudeRow(
        location=ctx.location(row["location"]),
        amplitude=text,
        ratio=ctx.ratio(ratio) if ratio is not None else "-",
        strongest=ratio == 1.0,
    )


def _spectrum(ctx: _Ctx, diagnosis: DiagnosisPayload) -> SpectrumChart | None:
    spectrum = diagnosis["spectrum"]
    if spectrum is None or not spectrum["peaks"]:
        return None
    markers = tuple(sorted(spectrum["order_markers"].items(), key=lambda item: item[1]))
    top_hz = max(
        [peak["hz"] for peak in spectrum["peaks"]]
        + [hz for code, hz in markers if code in {"T1", "T2", "P1", "E1", "E2"}]
    )
    return SpectrumChart(
        title=ctx.t(
            "SPECTRUM_TITLE",
            location=ctx.location(spectrum["location"]),
            speeds=ctx.speed_range(spectrum["speed_min_kmh"], spectrum["speed_max_kmh"]),
        ),
        floor_label=ctx.t("SPECTRUM_FLOOR"),
        floor_mg=spectrum["floor_mg"],
        peaks=tuple((peak["hz"], peak["amplitude_mg"]) for peak in spectrum["peaks"]),
        markers=markers,
        highlight=diagnosis["order_code"],
        x_max_hz=min(200.0, top_hz * 1.15),
    )


def _speed_chart(ctx: _Ctx, diagnosis: DiagnosisPayload) -> SpeedChart | None:
    points = diagnosis["amplitude_vs_speed"]
    speeds = [point["speed_kmh"] for point in points]
    if not speeds or max(speeds) - min(speeds) < _SPEED_SWEEP_MIN_KMH:
        return None
    order = [row["location"] for row in diagnosis["location_amplitudes"]]
    by_location: dict[str, list[tuple[float, float]]] = {}
    for point in points:
        by_location.setdefault(point["location"], []).append(
            (point["speed_kmh"], point["amplitude_mg"])
        )
    ranked = sorted(by_location, key=lambda loc: order.index(loc) if loc in order else len(order))
    return SpeedChart(
        title=ctx.t("SPEED_CHART_TITLE", order=diagnosis["order_code"] or ""),
        series=tuple(
            SpeedSeries(
                label=ctx.location(location),
                points=tuple(sorted(by_location[location])),
                strongest=index == 0,
            )
            for index, location in enumerate(ranked[:_MAX_SPEED_SERIES])
        ),
    )


def _ruled_out(ctx: _Ctx, diagnosis: DiagnosisPayload) -> tuple[str, ...]:
    lines: list[str] = []
    for check in diagnosis["source_checks"]:
        key = ctx.source_key(check["source"])
        if key is None or check["status"] == "candidate":
            continue
        reason = check["reason"] or ""
        if check["status"] == "not_applicable":
            lines.append(f"{ctx.t('SOURCE_COMBUSTION_ENGINE')}: {ctx.t('NOT_APPLICABLE_ELECTRIC')}")
            continue
        if check["status"] == "not_testable":
            detail = ctx.t(_NOT_TESTABLE_KEYS[reason])
        elif check["status"] == "ruled_out_estimated":
            detail = ctx.t(_RULED_OUT_ESTIMATED_KEYS[reason])
        elif reason in ("stayed_in_neutral", "stopped_in_neutral"):
            detail = ctx.t(f"RULED_OUT_{reason.upper()}")
        else:
            detail = ctx.t(_RULED_OUT_KEYS[key])
        lines.append(f"{ctx.t(f'SOURCE_{key}')}: {detail}")
    return tuple(lines)


def _shop(ctx: _Ctx, diagnosis: DiagnosisPayload) -> tuple[str, ...]:
    verdict = diagnosis["verdict"]
    if verdict == "no_fault":
        return (ctx.t("SHOP_NO_FAULT"),)
    if verdict == "weak_evidence":
        return (ctx.t("SHOP_WEAK"),)
    key = ctx.source_key(diagnosis["source"])
    if key is None:
        return (ctx.t("SHOP_OTHER", zone=ctx.zone(diagnosis)),)
    lines = [ctx.t(line) for line in _SHOP_KEYS[key]]
    if diagnosis["order_code"] == "T2":
        lines.append(ctx.t("SHOP_TIRE_T2"))
    return tuple(lines)


# -- quality ---------------------------------------------------------------------


def _quality(ctx: _Ctx, analysis: AnalysisSummary, metadata: RunMetadata) -> QualitySection:
    checks = tuple(
        QualityCheck(
            label=ctx.t(check["check_key"]),
            state=ctx.t("QUALITY_PASS" if check["state"] == "pass" else "QUALITY_WARN"),
            passed=check["state"] == "pass",
            detail=suitability_check_detail(ctx.lang, check),
        )
        for check in analysis["run_suitability"]
    )
    stated = warning_codes_stated_by_checks(analysis["run_suitability"])
    warnings = tuple(
        ctx.t_or(
            f"QUALITY_WARNING_{warning['code'].upper()}",
            resolve_i18n(ctx.lang, warning["title"], tr=ctx.t),
        )
        for warning in analysis["warnings"]
        if warning["code"] not in stated
    )
    rate = analysis["raw_sample_rate_hz"]
    traceability = (
        Fact(ctx.t("TRACE_RUN"), analysis["run_id"]),
        Fact(ctx.t("TRACE_SENSOR"), analysis.get("sensor_model") or metadata.sensor_model),
        Fact(
            ctx.t("TRACE_FIRMWARE"),
            analysis.get("firmware_version") or metadata.firmware_version or "-",
        ),
        Fact(ctx.t("TRACE_SAMPLE_RATE"), f"{ctx.num(rate)} Hz" if rate else "-"),
        Fact(ctx.t("TRACE_VERSION"), __version__),
    )
    all_passed = all(check.passed for check in checks) and not warnings
    footer = " · ".join(
        [ctx.t("QUALITY_ALL_PASSED")] + [f"{fact.label} {fact.value}" for fact in traceability]
    )
    return QualitySection(
        title=ctx.t("QUALITY_TITLE"),
        all_passed=all_passed,
        footer_line=footer,
        header=(
            ctx.t("QUALITY_HEADER_CHECK"),
            ctx.t("QUALITY_HEADER_RESULT"),
            ctx.t("QUALITY_HEADER_DETAIL"),
        ),
        checks=checks,
        warnings=warnings,
        traceability=traceability,
    )
