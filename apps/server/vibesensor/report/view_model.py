"""Report view model: every string and number the PDF draws, built from one stored run.

Pure translation of the persisted analysis (``AnalysisSummary``, whose
``diagnosis`` block carries the verdict) plus the run metadata into localized
text. It never re-derives the verdict, levels, order labels, amplitudes, or
zones; the renderer in ``report/pdf.py`` only lays this out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from vibesensor._version import __version__
from vibesensor.common.time_utils import format_run_timestamp
from vibesensor.domain.engine_profile import EngineProfilePayload
from vibesensor.domain.locations import location_code_for_label
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.report.i18n import (
    format_speed,
    normalize_lang,
    resolve_i18n,
    speed_unit_label,
    tr,
)
from vibesensor.report.run_quality import (
    suitability_check_detail,
    warning_codes_stated_by_checks,
)
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.diagnosis_contracts import (
    DiagnosisAlternative,
    DiagnosisPayload,
    FeltCauseRow,
    FeltPayload,
    LocationAmplitudeRow,
    OrderFindingRow,
    ReferenceProvenanceValue,
    TestConditions,
    UnexplainedVibration,
)
from vibesensor.summary.phases import PHASE_I18N_KEYS
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_SENSOR_LOOSE_MOUNT,
    WARNING_CODE_SPEED_MISSING,
)

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
    "SpectrumMarker",
    "SpeedChart",
    "SpeedSeries",
    "WorksheetRow",
    "build_owner_page",
    "build_report_view",
]

_NBSP = "\u00a0"
_SPEED_SWEEP_MIN_KMH = 30.0
_DOMINANT_RATIO = 1.5
_MAX_SPEED_SERIES = 4
_MAX_AMPLITUDE_ROWS = 8  # strongest first; keeps the workshop page on one sheet
_SOURCE_KEYS = {
    "wheel/tire": "WHEEL",
    "driveline": "DRIVELINE",
    "engine": "ENGINE",
    "brakes": "BRAKES",
}
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
    "single_wheel_sensor": "WEAK_SINGLE_WHEEL_SENSOR",
    "coast_test_contradicts": "WEAK_COAST_CONTRADICTS",
    "manual_speed": "WEAK_MANUAL_SPEED",
    "loose_mount": "WEAK_LOOSE_MOUNT",
}
# Why locations could not be compared: shown with every verdict, not just a weak one.
# Reasons about the sensors themselves: a fault's description states them too.
_SENSOR_REASONS = ("single_sensor", "single_wheel_sensor", "loose_mount")
_SPEED_DEPENDENCE_KEYS = {
    "vehicle_speed": "SPEED_DEPENDENCE_VEHICLE",
    "engine_speed": "SPEED_DEPENDENCE_ENGINE",
}
_SPEED_SOURCE_KEYS = {
    "gps": "SPEED_SOURCE_GPS",
    "obd2": "SPEED_SOURCE_OBD",
    "manual": "SPEED_SOURCE_MANUAL",
    "fallback_manual": "SPEED_SOURCE_FALLBACK_MANUAL",
    # The live source the user chose never gave a speed during the run.
    "gps_unaligned": "SPEED_SOURCE_GPS_NO_SPEED",
    "obd2_unaligned": "SPEED_SOURCE_OBD_NO_SPEED",
}
# Speeds entered by hand (the analysis's ``speed_typed_in``); reports never import analysis.
_TYPED_IN_SPEED_SOURCES = frozenset({"manual", "fallback_manual"})
_RECAPTURE_KEYS = ("RECAPTURE_ROAD", "RECAPTURE_SWEEP", "RECAPTURE_HOLD", "RECAPTURE_COAST")
# An EV cannot coast in neutral: its motor stays coupled to the wheels.
_RECAPTURE_KEYS_EV = ("RECAPTURE_ROAD", "RECAPTURE_SWEEP", "RECAPTURE_HOLD")
_RECAPTURE_KEYS_BRAKES = ("RECAPTURE_ROAD", "RECAPTURE_BRAKE")
# The speeds the test-drive tips name (the guided test's sweep and firm stops).
_BRAKE_TEST_FROM_KMH = 100.0
_BRAKE_TEST_TO_KMH = 40.0
_SWEEP_FROM_KMH = 50.0
_SWEEP_TO_KMH = 120.0
# An EV's motor turns at the driveshaft order (wheel speed x reduction ratio), so
# the driveline family reads as the motor and P1/P2 as motor revolutions.
_EV_ORDER_CODES = frozenset({"P1", "P2"})
_RPM_KEYS = {
    "measured": "RPM_MEASURED",
    "estimated_top_gear": "RPM_ESTIMATED_TOP_GEAR",
    "none": "RPM_NONE",
}
# A car without a propshaft (front-wheel drive, e-AWD hybrid) has its own
# driveline wording: the gearbox output shaft turns at P1/P2 (wheel speed x
# final drive); its drive shafts turn at wheel speed.
_NO_PROPSHAFT_KEYS = frozenset(
    {
        "ALT_DRIVELINE",
        "ORDER_P1",
        "ORDER_P2",
        "RULED_OUT_DRIVELINE",
        "WS_NONE",
        "WS_PEAK_ONLY",
        "WEAK_NARROW_SPEED",
    }
)
# The catalog suffix of a driveline fault's cause and step, per the parts to check
# (``driveline_parts``); a rear-wheel-drive car, or one without a layout, keeps
# the propshaft wording. Alone, ``front_drive`` is a car without a propshaft: its
# gearbox output shaft, final-drive pinion and differential bearings turn at the
# order. Next to ``propshaft_rear`` it is an AWD car's front axle, driven like the
# rear one by a propshaft (longitudinal AWD such as xDrive or quattro) into its
# differential pinion.
_DRIVELINE_PARTS_SUFFIX = {
    ("front_drive",): "_FRONT",
    ("front_drive", "propshaft_rear"): "_FRONT_REAR",
    ("propshaft_rear", "front_drive"): "_REAR_FRONT",
}
_DRIVELINE_SHOP_KEYS = {
    "front_drive": ("SHOP_DRIVELINE_FRONT_DIFF",),
    "front_drive_awd": ("SHOP_DRIVELINE_FRONT_PROPSHAFT",),
    "propshaft_rear": (
        "SHOP_DRIVELINE_RUNOUT",
        "SHOP_DRIVELINE_ANGLES",
        "SHOP_DRIVELINE_REAR_DIFF",
    ),
}
_SHOP_KEYS = {
    "WHEEL": (
        "SHOP_TIRE_BALANCE",
        "SHOP_TIRE_ROAD_FORCE",
        "SHOP_TIRE_MATCH",
        "SHOP_TIRE_RUNOUT",
    ),
    "DRIVELINE": ("SHOP_DRIVELINE_RUNOUT", "SHOP_DRIVELINE_ANGLES", "SHOP_DRIVELINE_ORDERS"),
    "ENGINE": ("SHOP_ENGINE_MOUNTS", "SHOP_ENGINE_ORDERS", "SHOP_ENGINE_MISFIRE"),
    "MOTOR": ("SHOP_MOTOR_MOUNTS", "SHOP_MOTOR_BALANCE", "SHOP_MOTOR_ORDERS"),
    "BRAKES": ("SHOP_BRAKES_RUNOUT", "SHOP_BRAKES_THICKNESS", "SHOP_BRAKES_HUB"),
}
_RULED_OUT_KEYS = {
    "WHEEL": "RULED_OUT_WHEEL",
    "DRIVELINE": "RULED_OUT_DRIVELINE",
    "ENGINE": "RULED_OUT_ENGINE",
    "MOTOR": "RULED_OUT_MOTOR",
    "BRAKES": "RULED_OUT_BRAKES",
}
_NOT_TESTABLE_KEYS = {
    "no_tire_reference": "NOT_TESTABLE_TIRE",
    "no_drive_reference": "NOT_TESTABLE_DRIVE",
    "no_engine_reference": "NOT_TESTABLE_ENGINE",
    "manual_speed": "NOT_TESTABLE_MANUAL_SPEED",
    "speed_missing": "NOT_TESTABLE_SPEED_MISSING",
    "engine_not_running": "NOT_TESTABLE_ENGINE_NOT_RUNNING",
    "same_rhythm_as_candidate": "NOT_TESTABLE_SAME_RHYTHM",
    "no_braking": "NOT_TESTABLE_NO_BRAKING",
}
_RULED_OUT_ESTIMATED_KEYS = {
    "estimated_final_drive": "RULED_OUT_ESTIMATED_FINAL_DRIVE",
    "estimated_top_gear": "RULED_OUT_ESTIMATED_TOP_GEAR",
    "top_gear_assumed": "RULED_OUT_ENGINE_TOP_GEAR",
    "engine_may_be_off": "RULED_OUT_ENGINE_MAY_BE_OFF",
    "regen_braking": "RULED_OUT_REGEN_BRAKING",
}
# A run that compared no rhythm at all: the next step that fixes why.
_CHECKED_STATUSES = frozenset({"candidate", "ruled_out", "ruled_out_estimated"})
_NOT_CHECKED_STEP_KEYS = {
    "manual_speed": "STEP_NOT_CHECKED_MANUAL_SPEED",
    "speed_missing": "STEP_NOT_CHECKED_SPEED_MISSING",
    "no_tire_reference": "STEP_NOT_CHECKED_TIRE",
}
# Page 1 of a no-fault run: what each untested or estimate-based check leaves open,
# and how to close it; the short hedge names the estimate in the "checked" list.
_COULDNT_TEST_KEYS = {
    "no_tire_reference": "COULDNT_TEST_TIRE",
    "no_drive_reference": "COULDNT_TEST_DRIVE",
    "no_engine_reference": "COULDNT_TEST_ENGINE",
    "manual_speed": "COULDNT_TEST_MANUAL_SPEED",
    "speed_missing": "COULDNT_TEST_SPEED_MISSING",
    "engine_not_running": "COULDNT_TEST_ENGINE_NOT_RUNNING",
    "no_braking": "COULDNT_TEST_NO_BRAKING",
}
_CHECKED_LIMITED_KEYS = {
    "estimated_final_drive": "CHECKED_LIMITED_FINAL_DRIVE",
    "estimated_top_gear": "CHECKED_LIMITED_TOP_GEAR",
    "top_gear_assumed": "CHECKED_LIMITED_ENGINE_TOP_GEAR",
    "engine_may_be_off": "CHECKED_LIMITED_ENGINE_MAY_BE_OFF",
    "regen_braking": "CHECKED_LIMITED_REGEN_BRAKING",
}
_CHECKED_HEDGE_KEYS = {
    "estimated_final_drive": "CHECKED_HEDGE_FINAL_DRIVE",
    "estimated_top_gear": "CHECKED_HEDGE_TOP_GEAR",
    "top_gear_assumed": "CHECKED_HEDGE_ENGINE_TOP_GEAR",
    "engine_may_be_off": "CHECKED_HEDGE_ENGINE_MAY_BE_OFF",
    "regen_braking": "CHECKED_HEDGE_REGEN_BRAKING",
}
# The engine's own wording: measured RPM tests it without the tire size or ratios, and
# an estimated RPM always assumes top gear.
_ENGINE_CHECK_KEYS = {
    "COULDNT_TEST_TIRE": "COULDNT_TEST_ENGINE_TIRE",
    "COULDNT_TEST_DRIVE": "COULDNT_TEST_ENGINE_DRIVE",
    "CHECKED_HEDGE_FINAL_DRIVE": "CHECKED_HEDGE_ENGINE_FINAL_DRIVE",
    "CHECKED_LIMITED_FINAL_DRIVE": "CHECKED_LIMITED_ENGINE_FINAL_DRIVE",
}
# An EV's motor turns at wheel speed x its reduction ratio, which the car keeps as
# its final drive: the motor's wording names the reduction ratio.
_MOTOR_CHECK_KEYS = {
    "NOT_TESTABLE_DRIVE": "NOT_TESTABLE_MOTOR_DRIVE",
    "RULED_OUT_ESTIMATED_FINAL_DRIVE": "RULED_OUT_ESTIMATED_MOTOR_FINAL_DRIVE",
    "COULDNT_TEST_DRIVE": "COULDNT_TEST_MOTOR_DRIVE",
    "CHECKED_HEDGE_FINAL_DRIVE": "CHECKED_HEDGE_MOTOR_FINAL_DRIVE",
    "CHECKED_LIMITED_FINAL_DRIVE": "CHECKED_LIMITED_MOTOR_FINAL_DRIVE",
}
# A wheel or propshaft order not told apart from the diagnosed engine order: the
# engine order turns at its rhythm in top gear.
_ROAD_CHECK_KEYS = {"NOT_TESTABLE_SAME_RHYTHM": "NOT_TESTABLE_SAME_RHYTHM_ROAD"}
_SOURCE_CHECK_KEYS = {
    "ENGINE": _ENGINE_CHECK_KEYS,
    "MOTOR": _MOTOR_CHECK_KEYS,
    "WHEEL": _ROAD_CHECK_KEYS,
    "DRIVELINE": _ROAD_CHECK_KEYS,
}
# The other cause a hedged diagnosis names, per source family.
_ALTERNATIVE_KEYS = {"WHEEL": "ALT_WHEEL", "DRIVELINE": "ALT_DRIVELINE", "ENGINE": "ALT_ENGINE"}
# An engine order's own wording and next step, by why the engine excites it
# (domain/engine_profile.py); the firing rhythm comes first.
_ENGINE_ROLE_ORDER = ("firing", "imbalance")


# -- view types ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Fact:
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class DiagramMarker:
    """One sensor on the car diagram; ``ratio`` 1.0 is the strongest location.

    A run that found no vibration has no level to show: ``value`` is empty and
    ``ratio`` ``None``, so the diagram shows where the sensors were.
    """

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


OwnerTone = Literal["good", "caution", "strong", "moderate", "muted"]


@dataclass(frozen=True, slots=True)
class OwnerPage:
    """Page 1: verdict, one confidence level, plain description, what to do.

    History opens a run's diagnosis with this same page (``owner`` in the
    insights response), so the app and the PDF say the same thing.
    """

    verdict: str
    # The run's result in a few words ("Front-left wheel", "No significant
    # vibration"); History titles the run with it. The PDF does not draw it.
    result: str
    # The verdict box's color: "good" only when the run checked something and
    # found nothing; a run that checked nothing, or felt a vibration nothing
    # checked explains, is never shown as all clear. "caution" (amber): no
    # fault, but a sensor may be loose, which can hide one.
    tone: OwnerTone
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
    # How much of what the occupants feel the cause explains, and whether a
    # workshop would act on that level ("What the driver feels" in docs/metrics.md).
    felt_title: str | None
    felt: str | None
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
class FeltRow:
    """One cause's level at the felt reference sensor against the workshop level."""

    cause: str
    level: str
    share: str
    judged: str
    workshop: str
    first: bool


@dataclass(frozen=True, slots=True)
class AmplitudeRow:
    location: str
    amplitude: str
    ratio: str
    strongest: bool


@dataclass(frozen=True, slots=True)
class SpectrumMarker:
    """One order's frequency on the spectrum; the firing order is labelled as such."""

    code: str
    hz: float
    label: str


@dataclass(frozen=True, slots=True)
class SpectrumChart:
    title: str
    floor_label: str
    floor_mg: float | None
    peaks: tuple[tuple[float, float], ...]
    markers: tuple[SpectrumMarker, ...]
    highlight: str | None
    x_max_hz: float


@dataclass(frozen=True, slots=True)
class SpeedSeries:
    label: str
    # (speed in the chart's unit, amplitude in mg)
    points: tuple[tuple[float, float], ...]
    strongest: bool


@dataclass(frozen=True, slots=True)
class SpeedChart:
    title: str
    series: tuple[SpeedSeries, ...]
    speed_unit: str


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
    # The causes by their level where the occupants sit; no title: nothing to show.
    felt_title: str | None
    felt_header: tuple[str, ...]
    felt: tuple[FeltRow, ...]
    felt_note: str | None
    amplitude_title: str
    amplitude_header: tuple[str, str, str]
    amplitudes: tuple[AmplitudeRow, ...]
    # Under a no-fault run's table: its levels are the road's, not a vibration found.
    amplitude_note: str | None
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
    speed_unit: str = "kmh",
) -> ReportView:
    """Build the full report view for one stored run in ``lang`` (default: the run's).

    Times show in IANA ``time_zone`` (the user's) when given, else in the offset
    recorded with the run. Speeds show in the user's ``speed_unit`` (``kmh`` or
    ``mps``), as on the History page.
    """
    ctx = _context(analysis, lang or analysis.get("lang") or metadata.language, speed_unit)
    diagnosis = analysis["diagnosis"]
    return ReportView(
        lang=ctx.lang,
        title=ctx.t("REPORT_TITLE"),
        header=_header(ctx, analysis, metadata, time_zone),
        owner=_owner_page(ctx, analysis, diagnosis),
        mechanic=_mechanic_page(ctx, analysis, metadata, diagnosis),
        quality=_quality(ctx, analysis, metadata),
    )


def build_owner_page(analysis: AnalysisSummary, *, lang: str, speed_unit: str = "kmh") -> OwnerPage:
    """Page 1 of the report alone: what History opens a run's diagnosis with."""
    return _owner_page(_context(analysis, lang, speed_unit), analysis, analysis["diagnosis"])


def _context(analysis: AnalysisSummary, lang: str | None, speed_unit: str) -> _Ctx:
    conditions = analysis["diagnosis"]["conditions"]
    electric = conditions["fuel_type"] == "EV"
    return _Ctx(
        normalize_lang(lang),
        electric=electric,
        no_propshaft=not electric and conditions.get("propshaft") is False,
        layout_unknown=not electric and conditions.get("drive_layout") is None,
        speed_unit=speed_unit,
        engine=None if electric else conditions.get("engine_profile"),
        engine_roles={
            row["code"]: tuple(row["roles"]) for row in conditions.get("engine_orders", [])
        },
    )


# -- formatting ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Ctx:
    lang: str
    # A battery-electric car: "motor" wording, no engine, no neutral coast-down.
    electric: bool = False
    # An engined car without a propshaft: drive-shaft wording for the driveline.
    no_propshaft: bool = False
    # An engined car whose drive layout was not given: the propshaft wording, hedged.
    layout_unknown: bool = False
    # The user's speed unit: "kmh" or "mps".
    speed_unit: str = "kmh"
    # The engine's layout and cylinders, when known, and why it excites each
    # engine order the run tested (by order code).
    engine: EngineProfilePayload | None = None
    engine_roles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

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

    @property
    def speed_unit_label(self) -> str:
        return speed_unit_label(self.speed_unit, self.lang)

    def in_unit(self, kmh: float) -> float:
        """A speed given in km/h, in the user's unit."""
        return kmh / 3.6 if self.speed_unit == "mps" else kmh

    def speed_number(self, kmh: float) -> str:
        """A speed given in km/h, as a whole number in the user's unit."""
        return self.num(self.in_unit(kmh))

    def speed(self, kmh: float) -> str:
        """A speed given in km/h, in the user's unit ("85 km/h", "24 m/s")."""
        return format_speed(kmh, self.speed_unit, self.lang)

    def test_speeds(self) -> dict[str, str]:
        """The speeds the test-drive tips name, in the user's unit."""
        return {
            "brake_from": self.speed(_BRAKE_TEST_FROM_KMH),
            "brake_to": self.speed(_BRAKE_TEST_TO_KMH),
            "sweep_from": self.speed_number(_SWEEP_FROM_KMH),
            "sweep_to": self.speed(_SWEEP_TO_KMH),
        }

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
        if diagnosis["source"] == "brakes":
            axle = zone in {"front_axle", "rear_axle"}
            return self.t(f"BRAKE_DISCS_{zone.upper()}" if axle and zone else "BRAKE_DISCS")
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
        if self.electric and code in _EV_ORDER_CODES:
            return f"ORDER_{code}_EV"
        return self.driveline_key(f"ORDER_{code}")

    def order_text(self, code: str) -> str:
        """An order code's plain wording; an engine order without its own: m times per turn."""
        key = self.order_key(code)
        text = self.t(key)
        if text == key and code.startswith("E"):
            times = float(code[1:])
            return self.t("ORDER_E_TIMES", times=self.num(times, 0 if times.is_integer() else 1))
        return text

    def engine_name(self) -> str | None:
        """The engine as a workshop names it (inline-6, V8); ``None`` when not known."""
        if self.engine is None:
            return None
        return self.t(f"ENGINE_{self.engine['layout'].upper()}", count=self.engine["cylinders"])

    def engine_role(self, code: str | None) -> str | None:
        """Why the known engine excites engine order *code*: firing, then imbalance."""
        if self.engine is None or code is None:
            return None
        roles = self.engine_roles.get(code, ())
        return next((role for role in _ENGINE_ROLE_ORDER if role in roles), None)

    def firing_code(self) -> str | None:
        """The known engine's firing order code (E3 for a six)."""
        if self.engine is None:
            return None
        return next(
            (code for code in self.engine_roles if self.engine_role(code) == "firing"), None
        )

    def driveline_key(self, key: str) -> str:
        """``key``, or its own wording for a car without a propshaft."""
        return f"{key}_NO_PROPSHAFT" if self.no_propshaft and key in _NO_PROPSHAFT_KEYS else key

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
        low_text, high_text = self.speed_number(low), self.speed_number(high)
        # A steady run reads "50 km/h", not "50–50 km/h".
        value = low_text if low_text == high_text else f"{low_text}–{high_text}"
        return f"{value}{_NBSP}{self.speed_unit_label}"


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


def _run_speeds(ctx: _Ctx, analysis: AnalysisSummary) -> str:
    """The run's speed range, or that it had no live speed at all."""
    speeds = analysis["speed_stats"]
    low, high = speeds["min_kmh"], speeds["max_kmh"]
    if low is None or high is None:
        return ctx.t("SPEEDS_NO_LIVE_SPEED")
    return ctx.speed_range(low, high)


def _header(
    ctx: _Ctx,
    analysis: AnalysisSummary,
    metadata: RunMetadata,
    time_zone: str | None,
) -> tuple[Fact, ...]:
    unknown = ctx.t("VALUE_UNKNOWN")
    return (
        Fact(ctx.t("HEADER_CAR"), _car_name(ctx, metadata)),
        Fact(ctx.t("HEADER_TIRES"), _tire_size(metadata) or unknown),
        Fact(
            ctx.t("HEADER_DATE"),
            ctx.t("HEADER_DATE_CLOCK_NOT_SET")
            if metadata.start_time_unverified
            else format_run_timestamp(
                analysis.get("start_time_utc") or metadata.start_time_utc,
                time_zone=time_zone,
                recorded_utc_offset_seconds=metadata.recorded_utc_offset_seconds,
            )
            or unknown,
        ),
        Fact(ctx.t("HEADER_SPEEDS"), _run_speeds(ctx, analysis)),
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
    result = ctx.t("RESULT_NO_FAULT")
    felt = _felt(ctx, diagnosis)
    tone = _owner_tone(diagnosis)
    if verdict == "no_fault":
        description, covered, not_covered = _coverage(ctx, analysis, diagnosis)
        loose = _loose_sensors(ctx, analysis)
        if loose is not None:
            description = f"{description} {loose}"
            tone = "caution"
        unexplained = _unexplained(diagnosis)
        if not _checked_anything(diagnosis):
            # Nothing was compared with any rhythm: no result, and what fixes that.
            headline = ctx.t("VERDICT_NOT_CHECKED")
            result = ctx.t("RESULT_NOT_CHECKED")
            next_step = ctx.t(
                _NOT_CHECKED_STEP_KEYS.get(_not_checked_reason(diagnosis), "STEP_NOT_CHECKED")
            )
        elif unexplained is not None:
            # A vibration was there; it just followed nothing the run could check.
            headline = ctx.t("VERDICT_UNEXPLAINED")
            result = ctx.t("RESULT_UNEXPLAINED")
            where = ctx.location(unexplained["location"])
            next_step = ctx.t("STEP_UNEXPLAINED", location=where)
    elif verdict == "weak_evidence":
        headline = ctx.t("VERDICT_WEAK")
        result = ctx.t("RESULT_WEAK")
        description = _description(ctx, diagnosis)
        candidate = ctx.t("VERDICT_WEAK_CANDIDATE", cause=_cause(ctx, diagnosis))
        reasons = tuple(_weak_reason(ctx, reason) for reason in diagnosis["weak_reasons"])
        reasons_title = ctx.t("WEAK_REASONS_TITLE") if reasons else None
        recapture = tuple(
            ctx.t(key, **ctx.test_speeds()) for key in _recapture_keys(ctx, diagnosis)
        )
        if _unlocated_wheel(diagnosis):
            recapture = (ctx.t("STEP_WHEEL_UNLOCATED"), *recapture)
        next_step = ctx.t("RECAPTURE_TITLE")
    else:
        step_key = _step_key(ctx, diagnosis)
        headline = ctx.t("VERDICT_LIKELY_CAUSE", cause=_cause(ctx, diagnosis))
        result = _fault_result(ctx, diagnosis)
        description = _description(ctx, diagnosis)
        for reason in _SENSOR_REASONS:
            if reason in diagnosis["weak_reasons"]:
                description = f"{description} {_weak_reason(ctx, reason)}".strip()
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
            if _propshaft_assumed(ctx, diagnosis):
                next_step = f"{next_step} {ctx.t('STEP_LAYOUT_UNKNOWN')}"
            fallback_step = _alternative_step(ctx, diagnosis) or ctx.t(
                "FALLBACK_PREFIX", step=ctx.t(f"{step_key}_FALLBACK", zone=zone)
            )
        verify = _verify(ctx, diagnosis)
    return OwnerPage(
        verdict=verdict,
        result=result,
        tone=tone,
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
        felt_title=ctx.t("FELT_TITLE") if felt else None,
        felt=felt,
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


def _recapture_keys(ctx: _Ctx, diagnosis: DiagnosisPayload) -> tuple[str, ...]:
    if diagnosis["source"] == "brakes":
        # Brake judder needs braking from speed, not a sweep or a coast-down.
        return _RECAPTURE_KEYS_BRAKES
    return _RECAPTURE_KEYS_EV if ctx.electric else _RECAPTURE_KEYS


def _unlocated_wheel(diagnosis: DiagnosisPayload) -> bool:
    """A wheel/tire fault felt strongest away from the wheels (no wheel sensor near it)."""
    return diagnosis["source"] == "wheel/tire" and diagnosis["zone"] not in _WHEEL_ZONES


def _corner(label: str | None) -> bool:
    return label is not None and location_code_for_label(label) in _WHEEL_CORNERS


def _cause(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    if _unlocated_wheel(diagnosis):
        if diagnosis["zone"] is None and _corner(diagnosis["location"]):
            # The only wheel with a sensor feels every wheel's imbalance.
            return ctx.t("CAUSE_WHEEL_ONE_SENSOR", location=ctx.location(diagnosis["location"]))
        return ctx.t("CAUSE_WHEEL_UNLOCATED", zone=ctx.zone(diagnosis))
    if diagnosis["source"] == "brakes":
        # The axle whose discs judder; without one, where it was felt.
        zone = diagnosis["zone"]
        if zone in {"front_axle", "rear_axle"}:
            return ctx.t("CAUSE_BRAKES", zone=ctx.t(f"ZONE_{zone.upper()}"))
        return ctx.t("CAUSE_BRAKES_UNLOCATED", zone=ctx.location(diagnosis["location"]))
    key = ctx.source_key(diagnosis["source"]) or "OTHER"
    if key == "DRIVELINE":
        key += _driveline_suffix(diagnosis)
    cause = ctx.t(f"CAUSE_{key}", zone=ctx.zone(diagnosis))
    alternative = diagnosis.get("alternative")
    if alternative is None:
        return cause
    return ctx.t("CAUSE_OR", cause=cause, other=_alternative_text(ctx, alternative))


def _owner_tone(diagnosis: DiagnosisPayload) -> OwnerTone:
    """The verdict's color: green only for a clean run that checked something.

    A no-fault run with a loose sensor is amber instead (``_owner_page``).
    """
    if diagnosis["verdict"] == "no_fault":
        clear = _checked_anything(diagnosis) and _unexplained(diagnosis) is None
        return "good" if clear else "muted"
    if diagnosis["verdict"] == "weak_evidence":
        return "muted"
    level = diagnosis["confidence_level"]
    if level == "strong" or level == "moderate":
        return level
    return "muted"


def _fault_result(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    """The cause in a few words: the wheel, axle, or part to look at."""
    source, zone = diagnosis["source"], diagnosis["zone"] or ""
    key = ctx.source_key(source)
    if source == "wheel/tire" and zone in _WHEEL_CORNERS:
        text = ctx.t(f"LOC_{zone.upper()}")
    elif source in {"wheel/tire", "brakes"} and zone in {"front_axle", "rear_axle"}:
        text = ctx.t(f"RESULT_{key}_{zone.upper()}")
    elif key is not None:
        text = ctx.t(f"SOURCE_{key}")
    else:
        # An order no source family owns: where it was strongest.
        text = ctx.location(diagnosis["location"])
    alternative = diagnosis.get("alternative")
    if alternative is not None and (other := ctx.source_key(alternative["source"])) is not None:
        text = ctx.t("RESULT_OR", result=text, other=ctx.t(f"SOURCE_{other}_NOUN"))
    return f"{text[:1].upper()}{text[1:]}"


def _alternative_text(ctx: _Ctx, alternative: DiagnosisAlternative) -> str:
    """The other cause of a hedged diagnosis, with its order code."""
    code = alternative["order_code"]
    key = ctx.source_key(alternative["source"]) or "OTHER"
    if key == "ENGINE" and (role := ctx.engine_role(code)) is not None:
        return ctx.t(f"ALT_ENGINE_{role.upper()}", engine=ctx.engine_name(), code=code)
    return ctx.t(ctx.driveline_key(_ALTERNATIVE_KEYS.get(key, "ALT_ENGINE")), code=code)


def _driveline_suffix(diagnosis: DiagnosisPayload) -> str:
    """Catalog suffix for the driveline parts to check (none: the propshaft wording)."""
    return _DRIVELINE_PARTS_SUFFIX.get(tuple(diagnosis.get("driveline_parts", ())), "")


def _propshaft_assumed(ctx: _Ctx, diagnosis: DiagnosisPayload) -> bool:
    """A driveline-order fault on an engined car whose drive layout was not given."""
    return (
        ctx.layout_unknown
        and diagnosis["source"] == "driveline"
        and diagnosis["order_code"] in _EV_ORDER_CODES
    )


def _step_key(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    code = diagnosis["order_code"]
    if diagnosis["source"] == "brakes":
        # Judder at the wheel order while braking: the discs, not the wheels.
        return "STEP_BRAKES"
    if not code:
        return "STEP_OTHER"
    if code in _EV_ORDER_CODES:
        if ctx.electric:
            return f"STEP_{code}_EV"
        if diagnosis["source"] == "driveline":
            return f"STEP_{code}{_driveline_suffix(diagnosis)}"
    if diagnosis["source"] == "engine" and (role := ctx.engine_role(code)) is not None:
        return f"STEP_ENGINE_{role.upper()}"
    return f"STEP_{code}"


def _alternative_step(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    """A hedged diagnosis's step for the other cause, should the coast-down point to it."""
    alternative = diagnosis.get("alternative")
    if alternative is None:
        return None
    other: DiagnosisPayload = {
        **diagnosis,
        "source": alternative["source"],
        "order_code": alternative["order_code"],
        "driveline_parts": [],
    }
    return ctx.t("STEP_HEDGE_OTHER", step=ctx.t(_step_key(ctx, other), zone=ctx.zone(other)))


def _confirm_check(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    """The cheap check for a Moderate fault; ``None`` when the guided coast-down already did it."""
    if diagnosis["source"] == "brakes":
        return ctx.t("CONFIRM_BRAKES", **ctx.test_speeds())
    if diagnosis["source"] == "wheel/tire":
        if diagnosis["zone"] in _WHEEL_CORNERS:
            return ctx.t("CONFIRM_WHEEL", zone=ctx.zone(diagnosis))
        if diagnosis["zone"] in {"front_axle", "rear_axle"}:
            return ctx.t("CONFIRM_AXLE")
        # On all four wheels a swap moves nothing, and with no axle named a swap
        # shows nothing; the coast-down still tells it from the engine.
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
        order = ctx.order_text(code)
        role = ctx.engine_role(code) if diagnosis["source"] == "engine" else None
        if role is not None:
            note = ctx.t(f"ORDER_NOTE_{role.upper()}", engine=ctx.engine_name())
            order = f"{order} ({note})"
        elif code == "E2" and ctx.engine is None:
            order = f"{order} ({ctx.t('ORDER_E2_NOTE')})"
        parts = [ctx.t("DESC_ORDER", order=order, hz=ctx.hz(hz), speed=ctx.speed(speed))]
    elif hz is not None:
        parts = [ctx.t("DESC_FREQUENCY", hz=ctx.hz(hz))]
    else:
        parts = []
    top = _strongest_two(diagnosis)
    if top:
        location = ctx.location(top[0]["location"])
        if len(top) == 2 and top[1]["ratio_to_strongest"] == 0:
            # The order's own level is over the floor at no other sensor: no ratio to give.
            parts.append(ctx.t("DESC_ONLY_MEASURED_AT", location=location))
        elif len(top) == 2 and top[1]["ratio_to_strongest"]:
            # The diagnosis's location leads a near tie, so it may be a little weaker.
            ratio = (top[0]["amplitude_mg"] or 0.0) / (top[1]["amplitude_mg"] or 1.0)
            if ratio >= _DOMINANT_RATIO:
                parts.append(ctx.t("DESC_STRONGER", ratio=ctx.ratio(ratio), location=location))
            else:
                other = ctx.location(top[1]["location"])
                parts.append(ctx.t("DESC_SIMILAR", location=location, other=other))
        elif len(diagnosis["location_amplitudes"]) == 1:
            # Nothing to compare with: the one sensor is not where it is strongest.
            parts.append(ctx.t("DESC_ONLY_SENSOR", location=location))
        else:
            parts.append(ctx.t("DESC_STRONGEST_AT", location=location))
    low, high = diagnosis["speed_min_kmh"], diagnosis["speed_max_kmh"]
    if low is not None and high is not None:
        if high - low >= 10.0:
            parts.append(
                ctx.t("DESC_PRESENT_RANGE", low=ctx.speed_number(low), high=ctx.speed(high))
            )
        else:
            parts.append(ctx.t("DESC_PRESENT_AT", speeds=ctx.speed_range(low, high)))
    if diagnosis["dominant_phase"] == "braking" and diagnosis["source"] == "brakes":
        parts.append(ctx.t("DESC_ONLY_WHILE_BRAKING"))
    sentence = ", ".join(parts)
    text = f"{sentence[:1].upper()}{sentence[1:]}." if sentence else ""
    dependence = diagnosis["speed_dependence"]
    if dependence is not None:
        text = f"{text} {ctx.t(_SPEED_DEPENDENCE_KEYS[dependence])}".strip()
    alternative = diagnosis.get("alternative")
    if alternative is not None:
        hedge = ctx.t("DESC_HEDGE", other=_alternative_text(ctx, alternative))
        text = f"{text} {hedge}".strip()
    elif any(check["reason"] == "same_rhythm_as_candidate" for check in diagnosis["source_checks"]):
        text = f"{text} {ctx.t('DESC_ENGINE_SAME_RHYTHM')}".strip()
    return text


_FELT_SEATS = frozenset(
    {"driver_seat", "front_passenger_seat", "rear_left_seat", "rear_center_seat", "rear_right_seat"}
)
# The share in words follows the number: "about half" around 50 %, "most" only
# clearly above half.
_FELT_SHARE_KEYS = (
    (0.9, "FELT_SHARE_ALL"),
    (0.6, "FELT_SHARE_MOST"),
    (0.4, "FELT_SHARE_HALF"),
    (0.0, "FELT_SHARE_PART"),
)
_FELT_WORKSHOP_KEYS = {"WHEEL": "FELT_WORKSHOP_WHEEL", "ENGINE": "FELT_WORKSHOP_ENGINE"}


def _felt_block(diagnosis: DiagnosisPayload) -> FeltPayload | None:
    """The run's felt ranking; ``None`` on a no-fault run or one analysed before it existed."""
    if diagnosis["verdict"] == "no_fault":
        return None
    return diagnosis.get("felt")


def _felt_measured(row: FeltCauseRow | None) -> FeltCauseRow | None:
    return row if row is not None and row["level_mg"] > 0 else None


def _felt(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str | None:
    """How much of what the occupants feel the diagnosed cause explains, and how
    a workshop would judge its level there."""
    felt = _felt_block(diagnosis)
    if felt is None:
        return None
    reference = felt["reference"]
    if reference is None:
        fallback = felt["fallback"]
        return ctx.t(f"FELT_FALLBACK_{fallback.upper()}") if fallback else None
    where = ctx.location(reference)
    row = _felt_measured(
        next((row for row in felt["causes"] if row["source"] == diagnosis["source"]), None)
    )
    if row is None:
        return ctx.t("FELT_NOT_MEASURED", location=where)
    share = row["share"] or 0.0
    share_key = next(key for floor, key in _FELT_SHARE_KEYS if share >= floor)
    low, high = row["speed_min_kmh"], row["speed_max_kmh"]
    parts = [
        ctx.t(
            "FELT_SHARE", location=where, share=ctx.t(share_key), speeds=ctx.speed_range(low, high)
        )
        if low is not None and high is not None
        else ctx.t("FELT_SHARE_ANY_SPEED", location=where, share=ctx.t(share_key))
    ]
    severity = _felt_severity(ctx, row, diagnosis["source"])
    if severity is not None:
        parts.append(severity)
        if location_code_for_label(reference) not in _FELT_SEATS:
            parts.append(ctx.t("FELT_NOT_SEAT", location=where))
    return " ".join(parts)


def _felt_severity(ctx: _Ctx, row: FeltCauseRow, source: str | None) -> str | None:
    severity, limit, normal = row["severity"], row["workshop_mg"], row["normal_mg"]
    if severity is None or limit is None:
        return None
    key = ctx.source_key(source) or ""
    if severity == "workshop":
        return ctx.t(_FELT_WORKSHOP_KEYS.get(key, "FELT_WORKSHOP"), limit=ctx.mg(limit))
    if severity == "normal" and normal is not None:
        return ctx.t("FELT_NORMAL", normal=ctx.mg(normal))
    below = ctx.t("FELT_BELOW_WORKSHOP", limit=ctx.mg(limit))
    return f"{below} {ctx.t('FELT_BELOW_WORKSHOP_WHEEL')}" if key == "WHEEL" else below


type _FeltTable = tuple[str | None, tuple[str, ...], tuple[FeltRow, ...], str | None]


def _felt_table(ctx: _Ctx, diagnosis: DiagnosisPayload) -> _FeltTable:
    """Page 2's felt table (title, header, rows, note): every cause at the felt
    reference against its workshop level; no title when there is nothing to show."""
    felt = _felt_block(diagnosis)
    if felt is None:
        return None, (), (), None
    reference = felt["reference"]
    if reference is None:
        note = _felt(ctx, diagnosis)
        return (ctx.t("FELT_TABLE_TITLE") if note else None), (), (), note
    where = ctx.location(reference)
    note = ctx.t("FELT_TABLE_BASIS")
    if location_code_for_label(reference) not in _FELT_SEATS:
        note = f"{note} {ctx.t('FELT_NOT_SEAT', location=where)}"
    header = tuple(
        ctx.t(key, location=where)
        for key in (
            "FELT_COL_CAUSE",
            "FELT_COL_LEVEL",
            "FELT_COL_SHARE",
            "FELT_COL_JUDGED",
            "FELT_COL_WORKSHOP",
        )
    )
    rows = tuple(_felt_row(ctx, row, first=index == 0) for index, row in enumerate(felt["causes"]))
    return ctx.t("FELT_TABLE_TITLE_AT", location=where), header, rows, note


def _felt_row(ctx: _Ctx, row: FeltCauseRow, *, first: bool) -> FeltRow:
    key = ctx.source_key(row["source"])
    source = ctx.t(f"SOURCE_{key}") if key else row["source"]
    measured = _felt_measured(row) is not None
    limit, normal = row["workshop_mg"], row["normal_mg"]
    workshop = ctx.mg(limit) if limit is not None else "-"
    if normal is not None:
        workshop = ctx.t("FELT_WORKSHOP_WITH_NORMAL", limit=workshop, normal=ctx.mg(normal))
    severity = row["severity"]
    return FeltRow(
        cause=f"{source} ({', '.join(row['order_codes'])})",
        level=ctx.mg(row["level_mg"]) if measured else ctx.t("FELT_NOT_MEASURABLE"),
        share=ctx.share(row["share"]) if row["share"] is not None and measured else "-",
        judged=ctx.t(f"FELT_JUDGED_{severity.upper()}") if severity else "-",
        workshop=workshop,
        first=first and measured,
    )


def _weak_reason(ctx: _Ctx, reason: str) -> str:
    key = _WEAK_REASON_KEYS.get(reason)
    return ctx.t(ctx.driveline_key(key)) if key is not None else reason


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
    key = _SOURCE_CHECK_KEYS.get(source_key, {}).get(key, key)
    # The brakes' texts name the speed to brake from.
    return ctx.t(key, **ctx.test_speeds())


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
        elif reason == "faint_only":
            # Found, but only at a healthy car's level: checked, and says so.
            checked.append(
                ctx.t("CHECKED_HEDGED", source=name, hedge=ctx.t("CHECKED_HEDGE_FAINT_ONLY"))
            )
            continue
        else:
            checked.append(name)
            continue
        gaps.append(ctx.t("NOT_COVERED_SOURCE", source=ctx.t(f"SOURCE_{key}"), detail=detail))
    unexplained = _unexplained(diagnosis)
    if unexplained is not None:
        description = ctx.t(
            "VERDICT_UNEXPLAINED_BODY",
            amplitude=ctx.mg(unexplained["amplitude_mg"]),
            location=ctx.location(unexplained["location"]),
        )
        if checked:
            description = (
                f"{description} {ctx.t('VERDICT_UNEXPLAINED_CHECKED', checked=ctx.join(checked))}"
            )
    elif checked:
        description = ctx.t("VERDICT_NO_FAULT_BODY", checked=ctx.join(checked))
    else:
        description = ctx.t(
            "VERDICT_NO_FAULT_BODY_NOTHING_CHECKED_EV"
            if ctx.electric
            else "VERDICT_NO_FAULT_BODY_NOTHING_CHECKED"
        )
    if not_checked and (checked or unexplained is not None):
        description = (
            f"{description} {ctx.t('VERDICT_NO_FAULT_NOT_CHECKED', sources=ctx.join(not_checked))}"
        )

    # The checks hold only where the run had live speed: say how long it had none.
    speed_gap = _speed_missing_gap(ctx, analysis)
    if speed_gap is not None:
        gaps.append(speed_gap)
    speeds = analysis["speed_stats"]
    phases = analysis["phase_info"]["phase_pcts"]
    driven = [phase for phase, share in phases.items() if share >= 1.0 and phase != "speed_unknown"]
    locations = [ctx.location(row["location"]) for row in diagnosis["location_amplitudes"]]
    low, high = speeds["min_kmh"], speeds["max_kmh"]
    sensors = ", ".join(locations) or ctx.t("VALUE_UNKNOWN")
    if low is None or high is None:
        # No live speed at all: no speed range or driving phase to name.
        covered = ctx.t("COVERED_BODY_NO_SPEED", locations=sensors)
    elif driven:
        covered = ctx.t(
            "COVERED_BODY",
            speeds=ctx.speed_range(low, high),
            phases=", ".join(ctx.phase(phase) for phase in driven),
            locations=sensors,
        )
    else:
        # Live speed for only a moment: a speed range but no driving phase to name.
        covered = ctx.t(
            "COVERED_BODY_NO_PHASES", speeds=ctx.speed_range(low, high), locations=sensors
        )
    if low is not None and low > 30.0:
        gaps.append(ctx.t("NOT_COVERED_BELOW", speed=ctx.speed(low)))
    if high is not None and high < 120.0:
        gaps.append(ctx.t("NOT_COVERED_ABOVE", speed=ctx.speed(high)))
    if "cruise" not in driven:
        gaps.append(ctx.t("NOT_COVERED_CRUISE"))
    # Braking is not coasting, nor the other way round: the brakes check above
    # says whether the drive braked.
    if not {"deceleration", "coast_down"} & set(driven):
        gaps.append(ctx.t("NOT_COVERED_COAST"))
    gaps.append(ctx.t("NOT_COVERED_NEVER", items=ctx.join(_never_analysed(ctx, diagnosis))))
    return description, covered, tuple(f"{gap[:1].upper()}{gap[1:]}" for gap in gaps)


def _speed_missing_gap(ctx: _Ctx, analysis: AnalysisSummary) -> str | None:
    """How long the run had no live speed, from its ``speed_missing`` warning."""
    for warning in analysis["warnings"]:
        title = warning["title"]
        if warning["code"] == WARNING_CODE_SPEED_MISSING and isinstance(title, dict):
            return ctx.t(
                "NOT_COVERED_SPEED_MISSING",
                seconds=str(title.get("seconds", "?")),
                source=str(title.get("source", "?")),
            )
    return None


def _loose_sensors(ctx: _Ctx, analysis: AnalysisSummary) -> str | None:
    """Which sensors may be loose, from the ``sensor_loose_mount`` warnings.

    A no-fault run states it on page 1: a loose sensor can hide a fault.
    """
    locations = [
        resolve_i18n(ctx.lang, title.get("location"), tr=ctx.t)
        for warning in analysis["warnings"]
        if warning["code"] == WARNING_CODE_SENSOR_LOOSE_MOUNT
        and isinstance(title := warning["title"], dict)
    ]
    if not locations:
        return None
    key = "VERDICT_NO_FAULT_LOOSE_MOUNT" if len(locations) == 1 else "VERDICT_NO_FAULT_LOOSE_MOUNTS"
    return ctx.t(key, locations=ctx.join(locations))


def _checked_anything(diagnosis: DiagnosisPayload) -> bool:
    """Whether the run compared any source's rhythm with what it measured."""
    return any(check["status"] in _CHECKED_STATUSES for check in diagnosis["source_checks"])


def _not_checked_reason(diagnosis: DiagnosisPayload) -> str:
    """Why the wheels (the first check) could not be checked; that fixes the rest too."""
    return next(
        (
            check["reason"]
            for check in diagnosis["source_checks"]
            if check["status"] == "not_testable" and check["reason"]
        ),
        "",
    )


def _unexplained(diagnosis: DiagnosisPayload) -> UnexplainedVibration | None:
    """The vibration a no-fault run felt that no checked cause explains: where, and how strong."""
    if diagnosis["verdict"] != "no_fault":
        return None
    return diagnosis["unexplained_vibration"]


def _never_analysed(ctx: _Ctx, diagnosis: DiagnosisPayload) -> list[str]:
    """Vibrations no run checks: no order covers them, whatever was driven.

    The analysis tracks the first and second wheel and propshaft orders, and the
    engine orders of the car's engine (E1 and E2 when it is not known), only
    while moving; measured RPM also places the engine orders at idle. A known
    engine's firing rhythm is analysed; without one a six's (E3) is not.
    """
    if ctx.electric:
        return [ctx.t("NEVER_MOTOR_ORDERS"), ctx.t("NEVER_WHEEL_BEARING")]
    items = [ctx.t("NEVER_ENGINE_MISFIRE")]
    if ctx.engine is None:
        items.append(ctx.t("NEVER_SIX_CYLINDER"))
    items.append(ctx.t("NEVER_WHEEL_BEARING"))
    if diagnosis["conditions"]["rpm_source"] != "measured":
        items.append(ctx.t("NEVER_IDLE_SHAKE"))
    return items


def _found_nothing(diagnosis: DiagnosisPayload) -> bool:
    """A no-fault run that felt no vibration either: its levels are the road's."""
    return diagnosis["verdict"] == "no_fault" and not diagnosis["unexplained_vibration"]


def _diagram(ctx: _Ctx, diagnosis: DiagnosisPayload) -> CarDiagram:
    """The sensors on the car, each with the level of the vibration the run found.

    A run that found none shows only where its sensors were: each location's
    strongest peak is then the road's broadband shake (at a wheel, mostly its
    wheel hop, about 2 g at motorway speed on any car), which a level beside a
    "No significant vibration" verdict would read as a fault.
    """
    found_nothing = _found_nothing(diagnosis)
    markers: list[DiagramMarker] = []
    for index, row in enumerate(diagnosis["location_amplitudes"]):
        code = location_code_for_label(row["location"])
        if code is None:
            continue
        if found_nothing:
            markers.append(
                DiagramMarker(
                    code=code,
                    label=ctx.location(row["location"]),
                    value="",
                    ratio=None,
                    strongest=False,
                )
            )
            continue
        amplitude = _detected_mg(row)
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
    felt_title, felt_header, felt_rows, felt_note = _felt_table(ctx, diagnosis)
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
        felt_title=felt_title,
        felt_header=felt_header,
        felt=felt_rows,
        felt_note=felt_note,
        amplitude_title=(
            ctx.t("AMPLITUDE_TITLE_ORDER", order=order_code)
            if diagnosis["amplitude_basis"] == "order" and order_code
            else ctx.t("AMPLITUDE_TITLE_OVERALL")
        ),
        amplitude_header=(ctx.t("AMP_LOCATION"), ctx.t("AMP_LEVEL"), ctx.t("AMP_RATIO")),
        amplitudes=tuple(
            _amplitude_row(ctx, row, first=index == 0)
            for index, row in enumerate(diagnosis["location_amplitudes"][:_MAX_AMPLITUDE_ROWS])
        ),
        amplitude_note=(
            ctx.t("AMPLITUDE_NOTE_ROAD")
            if _found_nothing(diagnosis) and diagnosis["location_amplitudes"]
            else None
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
    no_speed = speeds["min_kmh"] is None or speeds["max_kmh"] is None
    references = [Fact(ctx.t("COND_POWERTRAIN"), ctx.t(_powertrain_key(conditions)))]
    layout_key = _drive_layout_key(conditions)
    if layout_key is not None:
        references.append(Fact(ctx.t("COND_DRIVE_LAYOUT"), ctx.t(layout_key)))
    final_drive_text = _with_provenance(
        ctx,
        ctx.num(final_drive, 2) if final_drive is not None else None,
        conditions["final_drive_provenance"],
    )
    axle = conditions.get("final_drive_axle")
    if axle is not None and final_drive is not None:
        final_drive_text = f"{final_drive_text}, {ctx.t(f'FINAL_DRIVE_AXLE_{axle.upper()}')}"
    references += [
        Fact(ctx.t("COND_TIRE"), _with_provenance(ctx, tire, conditions["tire_provenance"])),
        Fact(
            ctx.t("COND_FINAL_DRIVE_EV" if ctx.electric else "COND_FINAL_DRIVE"),
            final_drive_text,
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
    if not ctx.electric:
        references.append(Fact(ctx.t("COND_ENGINE"), _engine_fact(ctx)))
    references.append(Fact(ctx.t("COND_SPEED_SOURCE"), speed_source))
    if not ctx.electric:
        references.append(Fact(ctx.t("COND_RPM"), ctx.t(_RPM_KEYS[conditions["rpm_source"]])))
    # Without live speed every second is "unknown speed": the speeds row says why.
    driving = () if no_speed else (Fact(ctx.t("COND_PHASES"), phases or unknown),)
    return (
        *references,
        Fact(ctx.t("HEADER_SPEEDS"), _run_speeds(ctx, analysis)),
        *driving,
        Fact(ctx.t("COND_GUIDED"), _guided_steps(ctx, diagnosis)),
        Fact(ctx.t("COND_SENSORS"), sensors or unknown),
    )


def _engine_fact(ctx: _Ctx) -> str:
    """The engine and the firing order the run tested, or that only E1/E2 were."""
    name, firing = ctx.engine_name(), ctx.firing_code()
    if name is None or firing is None:
        return ctx.t("COND_ENGINE_UNKNOWN")
    return ctx.t("COND_ENGINE_PROFILE", engine=f"{name[:1].upper()}{name[1:]}", firing=firing)


def _guided_steps(ctx: _Ctx, diagnosis: DiagnosisPayload) -> str:
    """The guided steps done, then those tapped that the drive's speed does not show."""

    def names(phases: Sequence[str]) -> str:
        return ", ".join(ctx.t(f"GUIDED_{phase.upper()}") for phase in phases)

    done = names(diagnosis["guided_phases"])
    undetected = diagnosis.get("guided_phases_undetected", [])
    if undetected:
        # A typed-in speed never changes, so no step can show in it: say so
        # rather than suggest the steps were driven wrong.
        typed_in = diagnosis["conditions"]["speed_source"] in _TYPED_IN_SPEED_SOURCES
        key = "GUIDED_NOT_CHECKABLE_MANUAL" if typed_in else "GUIDED_UNDETECTED"
        missing = ctx.t(key, steps=names(undetected))
        return f"{done}; {missing}" if done else f"{missing[:1].upper()}{missing[1:]}"
    return done or ctx.t("GUIDED_NONE")


def _powertrain_key(conditions: TestConditions) -> str:
    """The car's powertrain with what it means for the checks (PHEV: was the engine on?)."""
    fuel_type = conditions["fuel_type"]
    if fuel_type == "PHEV":
        measured = conditions["rpm_source"] == "measured"
        return "POWERTRAIN_PHEV_MEASURED" if measured else "POWERTRAIN_PHEV_ESTIMATED"
    return {"EV": "POWERTRAIN_EV", "ICE": "POWERTRAIN_ICE"}.get(
        fuel_type or "", "POWERTRAIN_UNKNOWN"
    )


def _drive_layout_key(conditions: TestConditions) -> str | None:
    """The drive layout line; an EV without one has no propshaft to assume, so none."""
    layout = conditions.get("drive_layout")
    if conditions["fuel_type"] == "EV":
        return f"DRIVE_LAYOUT_EV_{layout}" if layout is not None else None
    if layout is None:
        return "DRIVE_LAYOUT_UNKNOWN"
    if layout == "AWD" and conditions.get("propshaft") is False:
        return "DRIVE_LAYOUT_AWD_NO_PROPSHAFT"
    return f"DRIVE_LAYOUT_{layout}"


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
        order=f"{code} - {ctx.order_text(code)}",
        frequency=(
            f"{ctx.hz(hz)} @ {ctx.speed(speed)}"
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
        return ctx.t(ctx.driveline_key("WS_PEAK_ONLY"), hz=ctx.hz(diagnosis["frequency_hz"]))
    if any(check["reason"] == "faint_only" for check in diagnosis["source_checks"]):
        return ctx.t("WS_FAINT_ONLY")
    return ctx.t("WS_NONE_EV" if ctx.electric else ctx.driveline_key("WS_NONE"))


def _detected_mg(row: LocationAmplitudeRow) -> float | None:
    """The row's amplitude; ``None`` where the order did not reach that sensor.

    An order read at its line at a sensor it does not reach reads 0 mg (with a
    floor-relative dB that only reflects the floor), so it shows as not detected.
    """
    amplitude = row["amplitude_mg"]
    return amplitude if amplitude else None


def _amplitude_row(ctx: _Ctx, row: LocationAmplitudeRow, *, first: bool) -> AmplitudeRow:
    amplitude, db, ratio = _detected_mg(row), row["db_above_floor"], row["ratio_to_strongest"]
    if amplitude is None:
        text = ctx.t("AMP_NOT_DETECTED")
    elif db is not None:
        text = f"{ctx.mg(amplitude)} ({ctx.num(db)} dB)"
    else:
        text = ctx.mg(amplitude)
    return AmplitudeRow(
        location=ctx.location(row["location"]),
        amplitude=text,
        ratio=ctx.ratio(ratio) if ratio is not None and amplitude is not None else "-",
        strongest=first and amplitude is not None,
    )


def _spectrum(ctx: _Ctx, diagnosis: DiagnosisPayload) -> SpectrumChart | None:
    spectrum = diagnosis["spectrum"]
    if spectrum is None or not spectrum["peaks"]:
        return None
    firing = ctx.firing_code()
    markers = tuple(
        SpectrumMarker(
            code=code,
            hz=hz,
            label=f"{code} {ctx.t('SPECTRUM_FIRING')}" if code == firing else code,
        )
        for code, hz in sorted(spectrum["order_markers"].items(), key=lambda item: item[1])
    )
    # The chart reaches the first orders and every engine order the run tested;
    # P2 shows when it falls inside.
    top_hz = max(
        [peak["hz"] for peak in spectrum["peaks"]]
        + [
            marker.hz
            for marker in markers
            if marker.code in {"T1", "T2", "P1", "E1", "E2"} or marker.code in ctx.engine_roles
        ]
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
            (ctx.in_unit(point["speed_kmh"]), point["amplitude_mg"])
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
        speed_unit=ctx.speed_unit_label,
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
            detail = _check_text(ctx, _NOT_TESTABLE_KEYS, key, reason)
        elif check["status"] == "ruled_out_estimated":
            detail = _check_text(ctx, _RULED_OUT_ESTIMATED_KEYS, key, reason)
        elif reason in (
            "stayed_in_neutral",
            "stopped_in_neutral",
            "only_while_braking",
            "faint_only",
        ):
            detail = ctx.t(f"RULED_OUT_{reason.upper()}")
        else:
            detail = ctx.t(ctx.driveline_key(_RULED_OUT_KEYS[key]))
        lines.append(f"{ctx.t(f'SOURCE_{key}')}: {detail}")
    return tuple(lines)


def _shop(ctx: _Ctx, diagnosis: DiagnosisPayload) -> tuple[str, ...]:
    verdict = diagnosis["verdict"]
    if verdict == "no_fault" and not _checked_anything(diagnosis):
        return (ctx.t("SHOP_NOT_CHECKED"),)
    if verdict == "no_fault":
        unexplained = _unexplained(diagnosis)
        if unexplained is not None:
            return (ctx.t("SHOP_UNEXPLAINED", location=ctx.location(unexplained["location"])),)
        return (ctx.t("SHOP_NO_FAULT"),)
    if verdict == "weak_evidence":
        return (ctx.t("SHOP_WEAK"),)
    key = ctx.source_key(diagnosis["source"])
    if key is None:
        return (ctx.t("SHOP_OTHER", zone=ctx.zone(diagnosis)),)
    lines = [_shop_line(ctx, line) for line in _shop_keys(key, diagnosis)]
    if diagnosis["order_code"] == "T2":
        lines.append(ctx.t("SHOP_TIRE_T2"))
    alternative = diagnosis.get("alternative")
    if alternative is not None:
        lines.insert(
            0,
            ctx.t("SHOP_HEDGE", code=diagnosis["order_code"], other=alternative["order_code"]),
        )
    return tuple(lines)


def _shop_line(ctx: _Ctx, key: str) -> str:
    """One shop line; the engine-order comparison names a known engine's firing order."""
    firing = ctx.firing_code()
    if key == "SHOP_ENGINE_ORDERS" and firing is not None:
        return ctx.t("SHOP_ENGINE_ORDERS_PROFILE", firing=firing, engine=ctx.engine_name())
    return ctx.t(key)


def _shop_keys(key: str, diagnosis: DiagnosisPayload) -> tuple[str, ...]:
    """The shop lines; a driveline fault's follow its parts, the likelier first."""
    parts = diagnosis.get("driveline_parts", ())
    if key != "DRIVELINE" or not parts:
        return _SHOP_KEYS[key]
    if "propshaft_rear" in parts:
        shop_parts = ["front_drive_awd" if part == "front_drive" else part for part in parts]
        orders = "SHOP_DRIVELINE_ORDERS"
    else:
        shop_parts, orders = list(parts), "SHOP_DRIVELINE_ORDERS_NO_PROPSHAFT"
    return (*(line for part in shop_parts for line in _DRIVELINE_SHOP_KEYS[part]), orders)


# -- quality ---------------------------------------------------------------------


def _quality(ctx: _Ctx, analysis: AnalysisSummary, metadata: RunMetadata) -> QualitySection:
    checks = tuple(
        QualityCheck(
            label=ctx.t(check["check_key"]),
            state=ctx.t("QUALITY_PASS" if check["state"] == "pass" else "QUALITY_WARN"),
            passed=check["state"] == "pass",
            detail=suitability_check_detail(
                ctx.lang, check, electric=ctx.electric, speed_unit=ctx.speed_unit
            ),
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
