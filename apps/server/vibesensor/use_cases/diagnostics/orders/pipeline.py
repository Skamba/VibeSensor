"""Order-analysis orchestration above focused matching, rescue, scoring, and assembly helpers."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain import VibrationSource
from vibesensor.shared.constants.analysis import (
    CONSTANT_SPEED_STDDEV_KMH,
    ORDER_CONSTANT_SPEED_MIN_MATCH_RATE,
    ORDER_MIN_CONFIDENCE,
)
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics._reference_resolution import (
    _order_reference_spec_from_context,
)
from vibesensor.use_cases.diagnostics._sample_metrics import _sample_top_peaks
from vibesensor.use_cases.diagnostics._types import PhaseLabels, Sample
from vibesensor.use_cases.diagnostics.orders.finding_builder import (
    assemble_order_finding,
)
from vibesensor.use_cases.diagnostics.orders.heuristics import suppress_engine_aliases
from vibesensor.use_cases.diagnostics.orders.match_rate import (
    _compute_effective_match_rate,
)
from vibesensor.use_cases.diagnostics.orders.matching import (
    match_samples_for_hypothesis,
)
from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis, _order_hypotheses
from vibesensor.use_cases.diagnostics.orders.scoring import (
    OrderFindingBuildContext,
    score_order_finding,
)

# Maximum dominance ratio for splitting a finding into per-location findings.
# A ratio of 2.0 means the secondary location must be at least 50% as strong.
_MULTI_LOCATION_SPLIT_DOMINANCE = 2.0
# Floor for dominance ratio when computing the secondary-location confidence
# scale factor. Prevents division by values at or below 1.0.
_MIN_DOMINANCE_FOR_SCALE = 1.01


@dataclass(frozen=True, slots=True)
class OrderAnalysisRequest:
    """Typed inputs for one order-analysis pass across a prepared sample set."""

    context: RunMetadata
    samples: Sequence[Sample]
    speed_sufficient: bool
    steady_speed: bool
    speed_stddev_kmh: float | None
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
        "_speed_stddev_kmh",
        "_tire_circumference_m",
        "_engine_ref_sufficient",
        "_raw_sample_rate_hz",
        "_connected_locations",
        "_lang",
        "_per_sample_phases",
        "_cached_peaks",
        "_order_reference_spec",
    )

    def __init__(self, request: OrderAnalysisRequest) -> None:
        self._context = request.context
        self._samples = list(request.samples)
        self._speed_sufficient = request.speed_sufficient
        self._steady_speed = request.steady_speed
        self._speed_stddev_kmh = request.speed_stddev_kmh
        self._tire_circumference_m = request.tire_circumference_m
        self._engine_ref_sufficient = request.engine_ref_sufficient
        self._raw_sample_rate_hz = request.raw_sample_rate_hz
        self._connected_locations = set(request.connected_locations)
        self._lang = request.lang
        self._per_sample_phases = request.per_sample_phases
        self._order_reference_spec = _order_reference_spec_from_context(request.context)
        self._cached_peaks: list[list[tuple[float, float]]] = [
            _sample_top_peaks(sample) for sample in self._samples
        ]

    def analyze(self) -> list[DomainFinding]:
        """Run all hypothesis tests and return suppressed, ranked findings."""
        if self._raw_sample_rate_hz is None or self._raw_sample_rate_hz <= 0:
            return []

        findings: list[tuple[float, DomainFinding]] = []
        for hypothesis in _order_hypotheses():
            if not self._should_test(hypothesis):
                continue
            result = self._test_hypothesis(hypothesis)
            if result is not None:
                findings.append(result)

        findings = _split_multi_location_findings(findings)
        return suppress_engine_aliases(findings, min_confidence=ORDER_MIN_CONFIDENCE)

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

    def _test_hypothesis(
        self,
        hypothesis: OrderHypothesis,
    ) -> tuple[float, DomainFinding] | None:
        """Match, evaluate, and assemble a finding for one hypothesis."""
        match = match_samples_for_hypothesis(
            self._samples,
            self._cached_peaks,
            hypothesis,
            self._context,
            self._tire_circumference_m,
            self._per_sample_phases,
            self._lang,
        )
        if not match.is_eligible(
            feature_interval_s=self._context.feature_interval_s,
            steady_speed=self._steady_speed,
        ):
            return None

        constant_speed = (
            self._speed_stddev_kmh is not None
            and self._speed_stddev_kmh < CONSTANT_SPEED_STDDEV_KMH
        )
        min_match_rate = ORDER_CONSTANT_SPEED_MIN_MATCH_RATE if constant_speed else 0.25

        effective_match_rate, focused_speed_band, per_location_dominant = (
            _compute_effective_match_rate(
                match.match_rate,
                min_match_rate,
                match.possible_by_speed_bin,
                match.matched_by_speed_bin,
                match.possible_by_location,
                match.matched_by_location,
            )
        )
        if effective_match_rate < min_match_rate:
            return None

        build_context = OrderFindingBuildContext(
            effective_match_rate=effective_match_rate,
            focused_speed_band=focused_speed_band,
            per_location_dominant=per_location_dominant,
            match_rate=match.match_rate,
            min_match_rate=min_match_rate,
            constant_speed=constant_speed,
            steady_speed=self._steady_speed,
            connected_locations=self._connected_locations,
            lang=self._lang,
        )
        score = score_order_finding(
            hypothesis,
            match,
            context=build_context,
        )

        return assemble_order_finding(
            hypothesis,
            match,
            context=build_context,
            score=score,
        )


def _build_order_findings(request: OrderAnalysisRequest) -> list[DomainFinding]:
    """Build order-tracking findings by testing all hypotheses."""
    session = OrderAnalysisSession(request)
    return session.analyze()
