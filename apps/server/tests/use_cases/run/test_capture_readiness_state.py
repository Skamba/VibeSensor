from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import CaptureReadinessPolicy, RunContextSnapshot
from vibesensor.use_cases.run.capture_readiness_observation import CaptureReadinessObservation
from vibesensor.use_cases.run.capture_readiness_state import CaptureReadinessState


@dataclass(slots=True)
class _TrackedClient:
    client_id: str = "client-1"
    name: str = "Front left"
    firmware_version: str = "1.0.0"
    sample_rate_hz: int = 800
    location_code: str = "front_left_wheel"
    frames_total: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0


@dataclass(frozen=True, slots=True)
class _SpeedStatus:
    speed_source: str = "gps"
    effective_speed_kmh: float | None = 80.0
    last_update_age_s: float | None = 0.2
    fallback_active: bool = False


def _observation(
    *,
    now_mono: float,
    active_clients: tuple[_TrackedClient, ...],
    speed_status: _SpeedStatus | None = None,
) -> CaptureReadinessObservation:
    return CaptureReadinessObservation(
        observed_at_mono_s=now_mono,
        active_clients=active_clients,
        run_context=RunContextSnapshot(),
        speed_status=speed_status,
        obd_status=None,
    )


def test_capture_readiness_state_tracks_integrity_quiet_window() -> None:
    state = CaptureReadinessState(
        policy=CaptureReadinessPolicy(integrity_quiet_period_s=10.0),
    )
    client = _TrackedClient()

    initial = state.observe(_observation(now_mono=100.0, active_clients=(client,)))
    assert not initial.integrity.active
    assert initial.integrity.quiet_period_remaining_s is None

    issue = state.observe(
        _observation(
            now_mono=104.0,
            active_clients=(_TrackedClient(frames_dropped=2),),
        )
    )
    assert issue.integrity.active
    assert issue.integrity.frames_dropped == 2
    assert issue.integrity.quiet_period_remaining_s == 10.0

    expired = state.observe(_observation(now_mono=115.0, active_clients=(client,)))
    assert not expired.integrity.active
    assert expired.integrity.quiet_period_remaining_s is None


def test_capture_readiness_state_clears_speed_history_when_sample_is_invalid() -> None:
    state = CaptureReadinessState()
    client = _TrackedClient()

    first = state.observe(
        _observation(
            now_mono=100.0,
            active_clients=(client,),
            speed_status=_SpeedStatus(effective_speed_kmh=80.0),
        )
    )
    second = state.observe(
        _observation(
            now_mono=104.0,
            active_clients=(client,),
            speed_status=_SpeedStatus(effective_speed_kmh=82.0),
        )
    )
    reset = state.observe(
        _observation(
            now_mono=108.0,
            active_clients=(client,),
            speed_status=_SpeedStatus(effective_speed_kmh=10.0),
        )
    )

    assert len(first.speed_history) == 1
    assert len(second.speed_history) == 2
    assert reset.speed_history == ()
