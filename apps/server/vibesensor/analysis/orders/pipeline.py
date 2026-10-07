"""Order-analysis orchestration above focused matching, rescue, scoring, and assembly helpers."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from vibesensor.analysis._reference_resolution import (
    _NOT_MEASURED_RPM_SOURCES,
    ESTIMATED_RPM_SOURCE,
    _order_reference_spec_from_context,
)
from vibesensor.analysis._sample_metrics import _sample_top_peaks
from vibesensor.analysis._types import PhaseLabels, Sample
from vibesensor.analysis.constants import (
    MIN_ORDER_TRACKING_SLOPE,
    ORDER_MIN_CONFIDENCE,
)
from vibesensor.analysis.orders.brake_attribution import as_brake_finding, only_while_braking
from vibesensor.analysis.orders.finding_builder import (
    assemble_order_finding,
)
from vibesensor.analysis.orders.fixed_tones import without_fixed_tones
from vibesensor.analysis.orders.heuristics import suppress_engine_aliases
from vibesensor.analysis.orders.match_rate import (
    _compute_effective_match_rate,
    order_min_match_rate,
)
from vibesensor.analysis.orders.matching import (
    OrderMatchAccumulator,
    match_samples_for_hypothesis,
)
from vibesensor.analysis.orders.physics import OrderHypothesis, _order_hypotheses
from vibesensor.analysis.orders.scoring import (
    OrderFindingBuildContext,
    score_order_finding,
)
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import frequency_tracking_slope, trend_moves
from vibesensor.dsp.order_bands import ORDER_TOLERANCE_REL
from vibesensor.recording.run_schema import RunMetadata

# Maximum dominance ratio for splitting a finding into per-location findings.
# A ratio of 2.0 means the secondary location must be at least 50% as strong.
_MULTI_LOCATION_SPLIT_DOMINANCE = 2.0
# Floor for dominance ratio when computing the secondary-location confidence
# scale factor. Prevents division by values at or below 1.0.
_MIN_DOMINANCE_FOR_SCALE = 1.01


def _shared_fraction(
    peaks: frozenset[tuple[int, float]],
    other: frozenset[tuple[int, float]],
) -> float:
    return len(peaks & other) / len(peaks) if peaks else 0.0


def _rpm_measured(sample: Sample) -> bool:
    """The sample carries a measured engine RPM (an engine order is placed from it)."""
    return (
        sample.engine_rpm is not None
        and sample.engine_rpm > 0
        and sample.engine_rpm_source.strip().lower() not in _NOT_MEASURED_RPM_SOURCES
    )


def _measured_rpm(match: OrderMatchAccumulator) -> bool:
    """The engine order was placed from measured RPM, never from an estimate."""
    sources = match.ref_sources - {"missing"}
    return bool(sources) and ESTIMATED_RPM_SOURCE not in sources


def _rides_on(match: OrderMatchAccumulator, others: Sequence[OrderMatchAccumulator]) -> bool:
    """An order heard mostly where other orders' peaks already were, which went on without it.

    In a gear that puts an engine order near a wheel or propshaft order (a
    direct 1:1 gear, a six's E3 on P2 in a long top gear) the one order's window
    holds the other's tone. With measured RPM the two are told apart through
    the gear changes: when most of this order's matches have one of *others*'
    peaks inside its own window, and *others* went on through gears where this
    order did not follow, this order is their tone passing by, not a fault of
    its own.
    """
    if not others or not match.matched_points:
        return False
    on_others: set[int] = set()
    others_on_match = others_points = 0
    for other in others:
        other_hz = dict(
            zip(
                other.matched_sample_indices,
                (point.matched_hz for point in other.matched_points),
                strict=True,
            )
        )
        shared = {
            index
            for index, point in zip(match.matched_sample_indices, match.matched_points, strict=True)
            if (hz := other_hz.get(index)) is not None
            and abs(hz - point.predicted_hz) <= point.predicted_hz * ORDER_TOLERANCE_REL
        }
        on_others |= shared
        others_on_match += len(shared)
        others_points += len(other.matched_points)
    fraction = ORDER_CONFIDENCE_SETTINGS.wheel_alias_shared_peak_fraction
    return (
        len(on_others) / len(match.matched_points) >= fraction
        and others_on_match / others_points < fraction
    )


def _rides_on_another_order(
    hypothesis: OrderHypothesis,
    match: OrderMatchAccumulator,
    measured_engines: Sequence[OrderMatchAccumulator],
    road_orders: Sequence[OrderMatchAccumulator],
) -> bool:
    """With measured RPM, a road-speed order riding on an engine order, or the other way round."""
    if hypothesis.suspected_source in (VibrationSource.WHEEL_TIRE, VibrationSource.DRIVELINE):
        return _rides_on(match, measured_engines)
    if hypothesis.suspected_source is VibrationSource.ENGINE and _measured_rpm(match):
        return _rides_on(match, road_orders)
    return False


@dataclass(frozen=True, slots=True)
class OrderAnalysisRequest:
    """Typed inputs for one order-analysis pass across a prepared sample set."""

    context: RunMetadata
    samples: Sequence[Sample]
    speed_sufficient: bool
    steady_speed: bool
    speed_steadiness: float
    speed_constancy: float
    tire_circumference_m: float | None
    engine_ref_sufficient: bool
    raw_sample_rate_hz: float | None
    connected_locations: Collection[str]
    lang: str
    per_sample_phases: PhaseLabels | None = None


def _split_multi_location_findings(
    findings: list[tuple[float, DomainFinding]],
) -> list[tuple[float, DomainFinding]]:
    """Create per-location findings when a hypothesis matches at multiple strong corners.

    If a wheel/tire finding has alternative locations stored in its hotspot
    and the dominance ratio is below ``_MULTI_LOCATION_SPLIT_DOMINANCE``,
    a secondary finding is emitted for each alternative location that differs
    from the primary. The secondary finding receives a confidence scaled by
    ``1 / dominance_ratio`` so the weaker corner ranks below the stronger one
    while still surfacing in the findings list.
    """
    result: list[tuple[float, DomainFinding]] = list(findings)
    for score, finding in findings:
        if finding.source_normalized != VibrationSource.WHEEL_TIRE:
            continue
        hotspot = finding.location
        if hotspot is None:
            continue
        dom = finding.dominance_ratio
        if dom is None or dom >= _MULTI_LOCATION_SPLIT_DOMINANCE:
            continue
        primary = (finding.strongest_location or "").strip().lower()
        for alt_loc in hotspot.alternative_locations:
            alt_norm = alt_loc.strip().lower()
            if not alt_norm or alt_norm == primary:
                continue
            scale = 1.0 / max(dom, _MIN_DOMINANCE_FOR_SCALE)
            alt_hotspot = replace(
                hotspot,
                strongest_location=alt_loc,
                alternative_locations=(),
            )
            alt_finding = replace(
                finding,
                strongest_location=alt_loc,
                confidence=(finding.effective_confidence * scale),
                ranking_score=score * scale,
                location=alt_hotspot,
            )
            result.append((score * scale, alt_finding))
    return result


class OrderAnalysisSession:
    """Coordinates hypothesis testing across samples to produce order findings."""

    __slots__ = (
        "_context",
        "_samples",
        "_speed_sufficient",
        "_steady_speed",
        "_speed_steadiness",
        "_speed_constancy",
        "_tire_circumference_m",
        "_engine_ref_sufficient",
        "_raw_sample_rate_hz",
        "_connected_locations",
        "_lang",
        "_per_sample_phases",
        "_cached_peaks",
        "_speed_following_peaks",
        "_order_reference_spec",
        "_speed_moves",
    )

    def __init__(self, request: OrderAnalysisRequest) -> None:
        self._context = request.context
        self._samples = list(request.samples)
        self._speed_sufficient = request.speed_sufficient
        self._steady_speed = request.steady_speed
        self._speed_steadiness = request.speed_steadiness
        self._speed_constancy = request.speed_constancy
        self._tire_circumference_m = request.tire_circumference_m
        self._engine_ref_sufficient = request.engine_ref_sufficient
        self._raw_sample_rate_hz = request.raw_sample_rate_hz
        self._connected_locations = set(request.connected_locations)
        self._lang = request.lang
        self._per_sample_phases = request.per_sample_phases
        self._order_reference_spec = _order_reference_spec_from_context(request.context)
        self._speed_moves = trend_moves(
            (sample.t_s, sample.speed_kmh)
            for sample in self._samples
            if sample.t_s is not None and sample.speed_kmh is not None and sample.speed_kmh > 0
        )
        self._cached_peaks: list[list[tuple[float, float]]] = [
            _sample_top_peaks(sample) for sample in self._samples
        ]
        # A hypothesis placed from the speed is matched without the sensors'
        # fixed-frequency tones; an engine order placed from measured RPM may
        # ring steadily while the speed changes, so it keeps every peak.
        road_peaks = without_fixed_tones(self._samples, self._cached_peaks)
        self._speed_following_peaks = {
            "road": road_peaks,
            "engine": [
                raw if _rpm_measured(sample) else road
                for sample, raw, road in zip(
                    self._samples, self._cached_peaks, road_peaks, strict=True
                )
            ],
        }

    def analyze(self) -> list[DomainFinding]:
        """Run all hypothesis tests and return suppressed, ranked findings."""
        if self._raw_sample_rate_hz is None or self._raw_sample_rate_hz <= 0:
            return []

        matches = [
            (hypothesis, self._match_hypothesis(hypothesis))
            for hypothesis in _order_hypotheses(self._context.engine_profile)
            if self._should_test(hypothesis)
        ]
        wheel_peaks = frozenset().union(
            *(
                match.matched_peaks
                for hypothesis, match in matches
                if hypothesis.suspected_source is VibrationSource.WHEEL_TIRE
            )
        )
        evaluated: list[tuple[OrderHypothesis, OrderMatchAccumulator, tuple[float, DomainFinding]]]
        evaluated = []
        wheel_locked_engine_keys: set[str] = set()
        for hypothesis, match in matches:
            wheel_shared_fraction = (
                _shared_fraction(match.matched_peaks, wheel_peaks)
                if hypothesis.suspected_source is not VibrationSource.WHEEL_TIRE
                else 0.0
            )
            result = self._evaluate_hypothesis(
                hypothesis, match, wheel_shared_fraction=wheel_shared_fraction
            )
            if result is None:
                continue
            evaluated.append((hypothesis, match, result))
            if (
                hypothesis.suspected_source is VibrationSource.ENGINE
                and wheel_shared_fraction
                >= ORDER_CONFIDENCE_SETTINGS.wheel_alias_shared_peak_fraction
                and match.ref_sources == {ESTIMATED_RPM_SOURCE}
            ):
                wheel_locked_engine_keys.add(hypothesis.key)

        measured_engines = [
            match
            for hypothesis, match, _result in evaluated
            if hypothesis.suspected_source is VibrationSource.ENGINE and _measured_rpm(match)
        ]
        road_orders = (
            [
                match
                for hypothesis, match, _result in evaluated
                if hypothesis.suspected_source
                in (VibrationSource.WHEEL_TIRE, VibrationSource.DRIVELINE)
            ]
            if measured_engines
            else []
        )
        findings = _split_multi_location_findings(
            [
                result
                for hypothesis, match, result in evaluated
                if not _rides_on_another_order(hypothesis, match, measured_engines, road_orders)
            ]
        )
        return suppress_engine_aliases(
            findings,
            wheel_locked_engine_keys=frozenset(wheel_locked_engine_keys),
            min_confidence=ORDER_MIN_CONFIDENCE,
        )

    def _should_test(self, hypothesis: OrderHypothesis) -> bool:
        """Whether to test this hypothesis given available references."""
        spec = self._order_reference_spec
        if hypothesis.key.startswith("wheel_"):
            return self._speed_sufficient and (
                (spec is not None and spec.supports_wheel_reference)
                or (self._tire_circumference_m is not None and self._tire_circumference_m > 0)
            )
        if hypothesis.key.startswith("driveshaft_"):
            return self._speed_sufficient and (
                (spec is not None and spec.supports_driveshaft_reference)
                or (self._tire_circumference_m is not None and self._tire_circumference_m > 0)
            )
        if hypothesis.key.startswith("engine_"):
            return self._engine_ref_sufficient
        return True

    def _match_hypothesis(self, hypothesis: OrderHypothesis) -> OrderMatchAccumulator:
        engine = hypothesis.suspected_source is VibrationSource.ENGINE
        return match_samples_for_hypothesis(
            self._samples,
            self._speed_following_peaks["engine" if engine else "road"],
            hypothesis,
            self._context,
            self._tire_circumference_m,
            self._per_sample_phases,
            self._lang,
        )

    def _evaluate_hypothesis(
        self,
        hypothesis: OrderHypothesis,
        match: OrderMatchAccumulator,
        *,
        wheel_shared_fraction: float,
    ) -> tuple[float, DomainFinding] | None:
        """Evaluate and assemble a finding for one matched hypothesis.

        *wheel_shared_fraction* is the share of an engine or driveline order's
        matched peaks a wheel order matched too: from half, its frequency cannot
        tell it apart from that wheel order.
        """
        if not match.is_eligible(
            feature_interval_s=self._context.feature_interval_s,
            steady_speed=self._steady_speed,
        ):
            return None

        min_match_rate = order_min_match_rate(self._speed_constancy)

        effective_match_rate, focused_speed_band, per_location_dominant = (
            _compute_effective_match_rate(
                match.heard_match_rate,
                min_match_rate,
                match.possible_by_speed_bin,
                match.matched_by_speed_bin,
                match.possible_by_location,
                match.matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            return None
        slope = (
            frequency_tracking_slope([point for point, _floor in match.evidence])
            if self._speed_moves
            else None
        )
        if slope is not None and slope < MIN_ORDER_TRACKING_SLOPE:
            # The matches sit on a fixed-frequency tone the prediction swept
            # past; that tone stays a (persistent) peak finding of its own.
            return None

        build_context = OrderFindingBuildContext(
            effective_match_rate=effective_match_rate,
            focused_speed_band=focused_speed_band,
            per_location_dominant=per_location_dominant,
            match_rate=match.match_rate,
            min_match_rate=min_match_rate,
            constancy=self._speed_constancy,
            steadiness=self._speed_steadiness,
            connected_locations=self._connected_locations,
            lang=self._lang,
            wheel_shared_fraction=wheel_shared_fraction,
        )
        score = score_order_finding(
            hypothesis,
            match,
            context=build_context,
        )

        ranking_score, finding = assemble_order_finding(
            hypothesis,
            match,
            context=build_context,
            score=score,
        )
        if hypothesis.suspected_source is VibrationSource.WHEEL_TIRE and only_while_braking(
            match, self._samples, self._per_sample_phases
        ):
            finding = as_brake_finding(finding)
        return ranking_score, finding


def _build_order_findings(request: OrderAnalysisRequest) -> list[DomainFinding]:
    """Build order-tracking findings by testing all hypotheses."""
    session = OrderAnalysisSession(request)
    return session.analyze()
