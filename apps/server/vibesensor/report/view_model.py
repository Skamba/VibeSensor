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
from vibesensor.common.time_utils import format_timestamp_in_recorded_timezone
from vibesensor.domain.locations import location_code_for_label
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.report.i18n import normalize_lang, resolve_i18n, tr
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.diagnosis_contracts import (
    DiagnosisPayload,
    LocationAmplitudeRow,
    OrderFindingRow,
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
_RPM_KEYS = {"measured": "RPM_MEASURED", "estimated": "RPM_ESTIMATED", "none": "RPM_NONE"}
_SHOP_KEYS = {
    "WHEEL": ("SHOP_TIRE_ROAD_FORCE", "SHOP_TIRE_MATCH", "SHOP_TIRE_RUNOUT"),
    "DRIVELINE": ("SHOP_DRIVELINE_RUNOUT", "SHOP_DRIVELINE_ANGLES", "SHOP_DRIVELINE_ORDERS"),
    "ENGINE": ("SHOP_ENGINE_MOUNTS", "SHOP_ENGINE_ORDERS", "SHOP_ENGINE_MISFIRE"),
}
_RULED_OUT_KEYS = {
    "WHEEL": "RULED_OUT_WHEEL",
    "DRIVELINE": "RULED_OUT_DRIVELINE",
    "ENGINE": "RULED_OUT_ENGINE",
}
_NOT_TESTABLE_KEYS = {
    "no_tire_reference": "NOT_TESTABLE_TIRE",
    "no_drive_reference": "NOT_TESTABLE_DRIVE",
    "no_engine_reference": "NOT_TESTABLE_ENGINE",
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
    not_covered: str | None
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
) -> ReportView:
    """Build the full report view for one stored run in ``lang`` (default: the run's)."""
    ctx = _Ctx(normalize_lang(lang or analysis.get("lang") or metadata.language))
    diagnosis = analysis["diagnosis"]
    return ReportView(
        lang=ctx.lang,
        title=ctx.t("REPORT_TITLE"),
        header=_header(ctx, analysis, metadata),
        owner=_owner_page(ctx, analysis, diagnosis),
        mechanic=_mechanic_page(ctx, analysis, metadata, diagnosis),
        quality=_quality(ctx, analysis, metadata),
    )


# -- formatting ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ctx:
    lang: str

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
        if zone in _ZONE_KEYS:
            return self.t(f"ZONE_{zone.upper()}")
        if zone:
            # Another mounting point (a seat, the boot): the location it names.
            return self.t_or(f"LOC_{zone.upper()}", self.location(diagnosis["location"]))
        return self.location(diagnosis["location"])

    def phase(self, phase: str) -> str:
        key = PHASE_I18N_KEYS.get(phase)
        return self.t(key) if key else phase.replace("_", " ")

    def speed_range(self, low: float | None, high: float | None) -> str:
        if low is None or high is None:
            return self.t("VALUE_UNKNOWN")
        return f"{self.num(low)}–{self.num(high)}{_NBSP}km/h"


def _text(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def _source_key(source: str | None) -> str | None:
    return _SOURCE_KEYS.get(source or "")


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


def _header(ctx: _Ctx, analysis: AnalysisSummary, metadata: RunMetadata) -> tuple[Fact, ...]:
    speeds = analysis["speed_stats"]
    unknown = ctx.t("VALUE_UNKNOWN")
    return (
        Fact(ctx.t("HEADER_CAR"), _car_name(ctx, metadata)),
        Fact(ctx.t("HEADER_TIRES"), _tire_size(metadata) or unknown),
        Fact(
            ctx.t("HEADER_DATE"),
            format_timestamp_in_recorded_timezone(
                analysis.get("start_time_utc") or metadata.start_time_utc,
                metadata.recorded_utc_offset_seconds,
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
    description = ctx.t("VERDICT_NO_FAULT_BODY")
    candidate = reasons_title = covered = not_covered = confirm = None
    fallback_step = verify = None
    level_meaning = ctx.t(f"LEVEL_{level.upper()}_MEANING") if level else None
    reasons: tuple[str, ...] = ()
    recapture: tuple[str, ...] = ()
    next_step = ctx.t("STEP_NO_FAULT")
    if verdict == "no_fault":
        covered, not_covered = _coverage(ctx, analysis, diagnosis)
    elif verdict == "weak_evidence":
        headline = ctx.t("VERDICT_WEAK")
        description = _description(ctx, diagnosis)
        candidate = ctx.t("VERDICT_WEAK_CANDIDATE", cause=_cause(ctx, diagnosis))
        reasons = tuple(_weak_reason(ctx, reason) for reason in diagnosis["weak_reasons"])
        reasons_title = ctx.t("WEAK_REASONS_TITLE") if reasons else None
        recapture = tuple(ctx.t(key) for key in _RECAPTURE_KEYS)
        if _unlocated_wheel(diagnosis):
            recapture = (ctx.t("STEP_WHEEL_UNLOCATED"), *recapture)
        next_step = ctx.t("RECAPTURE_TITLE")
    else:
        step_key = _step_key(diagnosis)
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
    key = _source_key(diagnosis["source"]) or "OTHER"
    return ctx.t(f"CAUSE_{key}", zone=ctx.zone(diagnosis))


def _step_key(diagnosis: DiagnosisPayload) -> str:
    code = diagnosis["order_code"]
    return f"STEP_{code}" if code else "STEP_OTHER"


def _confirm_check(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    """The cheap check for a Moderate fault; ``None`` when the guided coast-down already did it."""
    if diagnosis["source"] == "wheel/tire":
        if diagnosis["zone"] in _WHEEL_CORNERS:
            return ctx.t("CONFIRM_WHEEL", zone=ctx.zone(diagnosis))
        if diagnosis["zone"] != "all_wheels":
            return ctx.t("CONFIRM_AXLE")
        # On all four wheels a swap moves nothing; the coast-down still tells it from the engine.
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
        order = ctx.t(f"ORDER_{code}")
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
        key = "DESC_PRESENT_RANGE" if high - low >= 10.0 else "DESC_PRESENT_AT"
        parts.append(ctx.t(key, low=ctx.num(low), high=ctx.num(high)))
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


def _coverage(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    diagnosis: DiagnosisPayload,
) -> tuple[str, str | None]:
    speeds = analysis["speed_stats"]
    phases = analysis["phase_info"]["phase_pcts"]
    driven = [phase for phase, share in phases.items() if share >= 1.0 and phase != "speed_unknown"]
    locations = [ctx.location(row["location"]) for row in diagnosis["location_amplitudes"]]
    covered = ctx.t(
        "COVERED_BODY",
        low=ctx.num(speeds["min_kmh"] or 0.0),
        high=ctx.num(speeds["max_kmh"] or 0.0),
        phases=", ".join(ctx.phase(phase) for phase in driven) or ctx.t("VALUE_UNKNOWN"),
        locations=", ".join(locations) or ctx.t("VALUE_UNKNOWN"),
    )
    gaps: list[str] = []
    low, high = speeds["min_kmh"], speeds["max_kmh"]
    if low is not None and low > 30.0:
        gaps.append(ctx.t("NOT_COVERED_BELOW", speed=ctx.num(low)))
    if high is not None and high < 120.0:
        gaps.append(ctx.t("NOT_COVERED_ABOVE", speed=ctx.num(high)))
    if "cruise" not in driven:
        gaps.append(ctx.t("NOT_COVERED_CRUISE"))
    if not {"deceleration", "coast_down"} & set(driven):
        gaps.append(ctx.t("NOT_COVERED_COAST"))
    if diagnosis["conditions"]["rpm_source"] != "measured":
        gaps.append(ctx.t("NOT_COVERED_RPM"))
    not_covered = "; ".join(gaps)
    return covered, (f"{not_covered[:1].upper()}{not_covered[1:]}." if not_covered else None)


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
    size = _tire_size(metadata) or unknown
    circumference = conditions["tire_circumference_m"]
    tire = (
        ctx.t("COND_CIRCUMFERENCE", size=size, circumference=ctx.num(circumference, 3))
        if circumference is not None
        else size
    )
    final_drive, gear = conditions["final_drive_ratio"], conditions["gear_ratio"]
    ratios = ctx.t(
        "COND_RATIOS_VALUE",
        final=ctx.num(final_drive, 2) if final_drive is not None else unknown,
        gear=ctx.num(gear, 2) if gear is not None else unknown,
    )
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
    return (
        Fact(ctx.t("COND_TIRE"), tire),
        Fact(ctx.t("COND_RATIOS"), ratios),
        Fact(ctx.t("COND_SPEED_SOURCE"), speed_source),
        Fact(ctx.t("COND_RPM"), ctx.t(_RPM_KEYS[conditions["rpm_source"]])),
        Fact(ctx.t("HEADER_SPEEDS"), ctx.speed_range(speeds["min_kmh"], speeds["max_kmh"])),
        Fact(ctx.t("COND_PHASES"), phases or unknown),
        Fact(
            ctx.t("COND_GUIDED"),
            ", ".join(ctx.t(f"GUIDED_{phase.upper()}") for phase in diagnosis["guided_phases"])
            or ctx.t("GUIDED_NONE"),
        ),
        Fact(ctx.t("COND_SENSORS"), sensors or unknown),
    )


def _worksheet_row(ctx: _Ctx, row: OrderFindingRow, *, diagnosed: bool) -> WorksheetRow:
    code = row["order_code"]
    hz, speed = row["frequency_hz"], row["reference_speed_kmh"]
    presence = row["presence_ratio"]
    return WorksheetRow(
        order=f"{code} - {ctx.t(f'ORDER_{code}')}",
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
    return ctx.t("WS_NONE")


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
            low=ctx.num(spectrum["speed_min_kmh"]),
            high=ctx.num(spectrum["speed_max_kmh"]),
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
        key = _source_key(check["source"])
        if key is None or check["status"] == "candidate":
            continue
        reason = check["reason"]
        if check["status"] == "not_testable":
            detail = ctx.t(_NOT_TESTABLE_KEYS.get(reason or "", "NOT_TESTABLE_TIRE"))
        elif reason == "rpm_estimated":
            detail = ctx.t("RULED_OUT_ENGINE_ESTIMATED")
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
    key = _source_key(diagnosis["source"])
    if key is None:
        return (ctx.t("SHOP_OTHER", zone=ctx.zone(diagnosis)),)
    lines = [ctx.t(line) for line in _SHOP_KEYS[key]]
    if diagnosis["order_code"] == "T2":
        lines.append(ctx.t("SHOP_TIRE_T2"))
    return tuple(lines)


# -- quality ---------------------------------------------------------------------


def _check_detail(ctx: _Ctx, check: Mapping[str, object]) -> str:
    """Plain meaning of one suitability check; a warning keeps its measured specifics."""
    key = str(check["check_key"]).removeprefix("SUITABILITY_CHECK_")
    passed = check["state"] == "pass"
    explanation = resolve_i18n(ctx.lang, check.get("explanation"), tr=ctx.t).strip()
    plain = ctx.t_or(f"QUALITY_{key}_{'PASS' if passed else 'WARN'}", explanation)
    if passed or not explanation or explanation == plain:
        return plain
    return f"{plain} {explanation}"


def _quality(ctx: _Ctx, analysis: AnalysisSummary, metadata: RunMetadata) -> QualitySection:
    checks = tuple(
        QualityCheck(
            label=ctx.t(check["check_key"]),
            state=ctx.t("QUALITY_PASS" if check["state"] == "pass" else "QUALITY_WARN"),
            passed=check["state"] == "pass",
            detail=_check_detail(ctx, check),
        )
        for check in analysis["run_suitability"]
    )
    warnings = tuple(
        ctx.t_or(
            f"QUALITY_WARNING_{warning['code'].upper()}",
            resolve_i18n(ctx.lang, warning["title"], tr=ctx.t),
        )
        for warning in analysis["warnings"]
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
