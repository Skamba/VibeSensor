"""Capture-readiness coordinator over observation, rolling state, and evaluation."""

from __future__ import annotations

from vibesensor.domain import CaptureReadiness, CaptureReadinessPolicy
from vibesensor.use_cases.run.capture_readiness_evaluator import evaluate_capture_readiness
from vibesensor.use_cases.run.capture_readiness_observation import CaptureReadinessObservation
from vibesensor.use_cases.run.capture_readiness_state import (
    CaptureReadinessState,
    CaptureReadinessStateConfig,
    build_capture_readiness_state_input,
)

__all__ = ["CaptureReadinessTracker"]


class CaptureReadinessTracker:
    """Own readiness state accumulation and delegate interpretation."""

    def __init__(self, *, policy: CaptureReadinessPolicy | None = None) -> None:
        self._policy = policy or CaptureReadinessPolicy()
        self._state = CaptureReadinessState(
            config=CaptureReadinessStateConfig(
                integrity_quiet_period_s=self._policy.integrity_quiet_period_s,
                stable_speed_dwell_s=self._policy.stable_speed_dwell_s,
            ),
        )

    def evaluate(self, observation: CaptureReadinessObservation) -> CaptureReadiness:
        state = self._state.observe(
            build_capture_readiness_state_input(
                policy=self._policy,
                observation=observation,
            ),
        )
        return evaluate_capture_readiness(
            policy=self._policy,
            observation=observation,
            state=state,
        )
