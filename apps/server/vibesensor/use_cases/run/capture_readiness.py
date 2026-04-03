"""Capture-readiness coordinator over observation, rolling state, and evaluation."""

from __future__ import annotations

from vibesensor.domain import CaptureReadiness, CaptureReadinessPolicy
from vibesensor.use_cases.run.capture_readiness_evaluator import evaluate_capture_readiness
from vibesensor.use_cases.run.capture_readiness_observation import CaptureReadinessObservation
from vibesensor.use_cases.run.capture_readiness_state import CaptureReadinessState

__all__ = ["CaptureReadinessTracker"]


class CaptureReadinessTracker:
    """Own readiness state accumulation and delegate interpretation."""

    def __init__(self, *, policy: CaptureReadinessPolicy | None = None) -> None:
        self._policy = policy or CaptureReadinessPolicy()
        self._state = CaptureReadinessState(policy=self._policy)

    def evaluate(self, observation: CaptureReadinessObservation) -> CaptureReadiness:
        return evaluate_capture_readiness(
            policy=self._policy,
            observation=observation,
            state=self._state.observe(observation),
        )
