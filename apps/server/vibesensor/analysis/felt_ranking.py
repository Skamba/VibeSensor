"""What the driver feels: the causes ranked by their level at the sensor nearest the occupants.

Nobody records a drive unless they feel a vibration, so the causes the run
found are ranked by what each one shakes where the occupants sit: its orders'
own level (``Finding.sensor_levels``) at the cabin or trunk sensor, every order
of its source added in power. That sensor cannot tell one wheel from another,
so the wheels are one cause there, however many corners the run named. Each
cause's share of what the causes found shake there, and how its level compares
with the limits workshops act on, go to the report. Without a cabin or trunk
sensor, or without order levels, the ranking by evidence stays. See "What the
driver feels" in docs/metrics.md.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from math import sqrt
from typing import Literal

from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import ConfidenceLevel, VibrationSource
from vibesensor.domain.locations import location_code_for_label
from vibesensor.domain.order_match import heard_speed_range
from vibesensor.dsp.window_spectrum import tone_line_level_g

__all__ = [
    "FELT_LOCATIONS",
    "WORKSHOP_LEVELS",
    "FeltAttribution",
    "FeltCause",
    "FeltFallback",
    "FeltRanking",
    "FeltSeverity",
    "WorkshopLevel",
    "felt_ranking",
    "rank_by_felt",
]

# The sensor locations nearest the occupants, the one a ranking reads first:
# a seat (where workshops measure: the driver's seat track), then the trunk (on
# the body behind the rear seats), then the propshaft tunnel (the cabin floor).
# Wheel, subframe, engine-bay and gearbox sensors sit on the source side of
# the bushings and mounts that keep a vibration out of the body.
FELT_LOCATIONS: tuple[str, ...] = (
    "driver_seat",
    "front_passenger_seat",
    "rear_left_seat",
    "rear_center_seat",
    "rear_right_seat",
    "trunk",
    "driveshaft_tunnel",
)

type FeltFallback = Literal["no_cabin_sensor", "no_order_levels"]
type FeltSeverity = Literal["workshop", "below_workshop", "normal"]


@dataclass(frozen=True, slots=True)
class WorkshopLevel:
    """A workshop's limit for one source's order: peak g on one axis of the driver's seat track.

    ``act_g``: from here a workshop repairs. ``normal_g``: up to here the level
    is normal; ``None`` where no source gives one.
    """

    act_g: float
    normal_g: float | None = None


# GM 20-NA-192 (2020; follows 19-NA-240), on the driver's seat track after a
# 10 min warm-up at 80-129 km/h: T1 on the Y axis consistently over 25 mg,
# service all wheel and tire assemblies (balance; road force under 30 lb front,
# 45 lb rear); under 25 mg, look elsewhere.
_WHEEL_SEAT_TRACK = WorkshopLevel(act_g=0.025)
WORKSHOP_LEVELS: dict[VibrationSource, WorkshopLevel] = {
    VibrationSource.WHEEL_TIRE: _WHEEL_SEAT_TRACK,
    # No published limit: the same seat-track level, an assumption to calibrate.
    VibrationSource.DRIVELINE: _WHEEL_SEAT_TRACK,
    VibrationSource.BRAKES: _WHEEL_SEAT_TRACK,
    # GM rough-idle diagnosis: an engine order at the seat track of 12 mg or
    # more points to the engine mounts; about 2 mg or less is normal. Measured
    # at idle; while driving an assumption to calibrate.
    VibrationSource.ENGINE: WorkshopLevel(act_g=0.012, normal_g=0.002),
}


@dataclass(frozen=True, slots=True)
class FeltAttribution:
    """How the diagnosis attributes the causes' orders, for the felt block it reports.

    ``ruled_out``: sources the diagnosis rules out (the neutral coast-down);
    they are not felt causes. ``line_of``: an order on another order's line
    (without measured RPM, an engine order turning with a wheel or propshaft
    order in top gear: ``{"E1": "T2"}``), one spectral line read twice.
    ``owner``: the source the diagnosis names; a line two causes share is
    its own, else the cause ranked first by evidence.
    """

    ruled_out: frozenset[VibrationSource] = frozenset()
    line_of: Mapping[str, str] = field(default_factory=dict)
    owner: VibrationSource | None = None


@dataclass(frozen=True, slots=True)
class FeltCause:
    """One source's level at the felt reference sensor; ``finding`` is its best-ranked top cause.

    ``order_levels_g``: each order of the source (code, its level at the
    reference, g); ``share``: its part of what the causes found heard at the
    same speeds shake there, ``None`` when it does not reach the reference.
    """

    finding: Finding
    order_levels_g: tuple[tuple[str, float], ...]
    speed_range_kmh: tuple[float, float] | None
    share: float | None = None

    @property
    def level_g(self) -> float:
        """The cause's level at the reference: its orders added in power."""
        return sqrt(sum(level * level for _code, level in self.order_levels_g))

    def peak_g(self, bin_hz: float) -> float:
        """The level as the peak of a tone on one axis, the scale workshop limits are on.

        The level adds the three axes in power, so this is the most any one
        axis can carry: an ISO 2631-1 style vector sum against a one-axis
        limit. *bin_hz*: the spectrum's bin width the level was read at.
        """
        return self.level_g / tone_line_level_g(1.0, bin_hz)

    def severity(self, bin_hz: float) -> FeltSeverity | None:
        """How the level compares with the workshop limit of its source; ``None``
        without a level or a limit."""
        limit = WORKSHOP_LEVELS.get(self.finding.suspected_source)
        peak = self.peak_g(bin_hz)
        if limit is None or peak <= 0:
            return None
        if peak >= limit.act_g:
            return "workshop"
        if limit.normal_g is not None and peak <= limit.normal_g:
            return "normal"
        return "below_workshop"


@dataclass(frozen=True, slots=True)
class FeltRanking:
    """The causes ranked by their level at the felt reference sensor (its location label).

    Without a reference (``fallback`` says why) the causes keep the ranking by
    evidence. Causes the reference does not measure come last.
    """

    reference: str | None
    fallback: FeltFallback | None
    causes: tuple[FeltCause, ...]


def _reference(findings: Sequence[Finding]) -> tuple[str | None, FeltFallback | None]:
    labels = {level.location for finding in findings for level in finding.sensor_levels}
    if not labels:
        return None, "no_order_levels"
    by_code = {location_code_for_label(label): label for label in sorted(labels)}
    for code in FELT_LOCATIONS:
        if code in by_code:
            return by_code[code], None
    return None, "no_cabin_sensor"


def _is_order_cause(finding: Finding) -> bool:
    return finding.is_diagnostic and finding.is_actionable and finding.order_code is not None


def _felt_level_g(finding: Finding, reference: str) -> float:
    """The order's level at *reference* where it stands out of the floor beside its line.

    A vibration is felt as one of its own where its line carries at least the
    floor's power over it (level >= floor, 3 dB); below, it is part of the
    road's rumble there, or a body mode the line sweeps over reads as it.
    """
    for level in finding.sensor_levels:
        if level.location == reference:
            return level.level_g if level.level_g >= level.floor_g else 0.0
    return 0.0


def _order_levels(
    cause: Finding, findings: Sequence[Finding], reference: str
) -> tuple[tuple[str, float], ...]:
    """Each order of the cause's source and its felt level at *reference* (g)."""
    levels: dict[str, float] = {}
    for member in (cause, *findings):
        code = member.order_code
        if code is None or member.suspected_source is not cause.suspected_source:
            continue
        if member is not cause and not member.should_surface:
            continue
        levels[code] = max(levels.get(code, 0.0), _felt_level_g(member, reference))
    return tuple(sorted(levels.items()))


def _overlap(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool:
    return a is None or b is None or (a[0] <= b[1] and b[0] <= a[1])


def _with_shares(causes: Sequence[FeltCause], line_of: Mapping[str, str]) -> list[FeltCause]:
    """Each measured cause's share of the power of the causes heard at overlapping speeds.

    Orders add in power: different frequencies do not interfere over a
    window. A line two causes share (two corners' T1; an engine order on a
    wheel order's line, ``line_of``) counts once.
    """
    shared: list[FeltCause] = []
    for cause in causes:
        if cause.level_g <= 0:
            shared.append(cause)
            continue
        lines: dict[str, float] = {}
        for other in causes:
            if other.level_g > 0 and _overlap(cause.speed_range_kmh, other.speed_range_kmh):
                for code, level in other.order_levels_g:
                    line = line_of.get(code, code)
                    lines[line] = max(lines.get(line, 0.0), level * level)
        share = min(1.0, cause.level_g**2 / sum(lines.values()))
        shared.append(FeltCause(cause.finding, cause.order_levels_g, cause.speed_range_kmh, share))
    return shared


def _attributed(causes: Sequence[FeltCause], attribution: FeltAttribution) -> list[FeltCause]:
    """Each line to one cause: the diagnosed source's where it shares it, else the
    first by evidence; a cause left with no line of its own is not one."""
    owners: dict[str, VibrationSource] = {}
    for cause in sorted(causes, key=lambda c: c.finding.suspected_source is not attribution.owner):
        for code, _level in cause.order_levels_g:
            owners.setdefault(attribution.line_of.get(code, code), cause.finding.suspected_source)
    kept: list[FeltCause] = []
    for cause in causes:
        source = cause.finding.suspected_source
        own = tuple(
            (code, level)
            for code, level in cause.order_levels_g
            if owners[attribution.line_of.get(code, code)] is source
        )
        if own:
            kept.append(FeltCause(cause.finding, own, cause.speed_range_kmh))
    return kept


def felt_ranking(
    top_causes: Sequence[Finding],
    findings: Sequence[Finding],
    attribution: FeltAttribution | None = None,
) -> FeltRanking:
    """The order causes among *top_causes* by their level at the felt reference sensor.

    With the diagnosis's *attribution* (the felt block it reports), the sources
    it rules out are left out and a line two causes share is one cause's.
    """
    reference, fallback = _reference(findings)
    if reference is None:
        return FeltRanking(reference=None, fallback=fallback, causes=())
    ruled_out = attribution.ruled_out if attribution is not None else frozenset()
    # One cause per source: its best-ranked top cause stands for it.
    representatives: dict[VibrationSource, Finding] = {}
    for cause in top_causes:
        if _is_order_cause(cause) and cause.suspected_source not in ruled_out:
            representatives.setdefault(cause.suspected_source, cause)
    causes = [
        FeltCause(
            finding=cause,
            order_levels_g=_order_levels(cause, findings, reference),
            speed_range_kmh=heard_speed_range(cause.matched_points),
        )
        for cause in representatives.values()
    ]
    if attribution is not None:
        causes = _attributed(causes, attribution)
    causes.sort(key=lambda cause: -cause.level_g)
    line_of = attribution.line_of if attribution is not None else {}
    return FeltRanking(
        reference=reference, fallback=None, causes=tuple(_with_shares(causes, line_of))
    )


def rank_by_felt(top_causes: Sequence[Finding], findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """*top_causes* ranked by what the driver feels, where a felt reference sensor measured.

    The causes whose source the reference measures come first, the strongest
    source there first (a source's causes in their ranking by evidence); then
    the others in their ranking by evidence. A Weak cause, which the report
    never acts on, stays after every Strong or Moderate one.
    """
    ranking = felt_ranking(top_causes, findings)
    if ranking.reference is None:
        return tuple(top_causes)
    power = {cause.finding.suspected_source: cause.level_g**2 for cause in ranking.causes}

    def key(finding: Finding) -> tuple[bool, bool, float]:
        felt = power.get(finding.suspected_source, 0.0) if _is_order_cause(finding) else 0.0
        return (finding.confidence_level is ConfidenceLevel.WEAK, felt <= 0, -felt)

    return tuple(sorted(top_causes, key=key))
