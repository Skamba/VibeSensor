from __future__ import annotations

import random

import pytest

from vibesensor.analysis.phase_segmentation import braking_intervals, speed_slopes_kmh_s
from vibesensor.recording.guided_brake_stops import GuidedBrakeStops
from vibesensor.recording.raw_capture import RawCaptureLossStats
from vibesensor.recording.run_schema import RunGuidedPhase


def test_recording_session_start_owns_context_snapshots_and_ingest_drop_baseline(
    make_logger,
) -> None:
    recorder = make_logger()
    active = recorder.registry.get("active")
    assert active is not None
    active.server_queue_drops = 2

    snapshot = recorder._recording_session.start_new_run()
    active.server_queue_drops = 5

    assert recorder.processor.flush_calls == [("active", "recording run start")]
    assert recorder._lifecycle.run_id == snapshot.run_id
    assert recorder._recording_session.run_context_snapshot(snapshot.run_id).analysis_settings
    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id)
    assert recorder._recording_session.ingest_drop_losses() == {
        "active": RawCaptureLossStats(udp_ingest_queue_drop_count=3),
    }


def test_recording_session_clear_stopped_run_drops_active_context(make_logger) -> None:
    recorder = make_logger()
    snapshot = recorder._recording_session.start_new_run()
    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id)

    recorder._recording_session.clear_stopped_run()

    assert recorder._recording_session.run_sensor_snapshots_for_run(snapshot.run_id) == ()
    assert recorder._recording_session.ingest_drop_losses() is None


def _clock(session):
    """Pin the run clock to exact floats so step times compare exactly."""
    now = [1000.0]
    session._live_start_mono_s = now[0]
    session._monotonic = lambda: now[0]
    return now


def test_guided_phases_close_each_step_when_the_next_starts(
    make_logger, history_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = make_logger(history_db=history_db)
    monkeypatch.setattr(recorder.post_analysis, "schedule", lambda _run_id: None)
    run_id = recorder.start_recording().run_id
    session = recorder._recording_session
    now = _clock(session)

    now[0] += 5.0
    session.mark_guided_phase("sweep")
    assert recorder.status().guided_phases_completed == ()
    now[0] += 20.0
    session.mark_guided_phase("hold")
    now[0] += 10.0
    session.mark_guided_phase("coast_down")
    assert session.current_guided_phase() == "coast_down"
    assert recorder.status().guided_phases_completed == ("sweep", "hold")
    now[0] += 8.0
    session.mark_guided_phase(None)

    assert session.current_guided_phase() is None
    assert session.guided_phases_for_run(run_id) == (
        RunGuidedPhase("sweep", 5.0, 25.0),
        RunGuidedPhase("hold", 25.0, 35.0),
        RunGuidedPhase("coast_down", 35.0, 43.0),
    )
    assert recorder.status().guided_phase is None
    # A reloaded Live page restores the finished guided test from the status.
    assert recorder.status().guided_phases_completed == ("sweep", "hold", "coast_down")

    # The finished run's stored metadata carries the guided phases for analysis.
    active = recorder.registry.get("active")
    assert active is not None
    active.frames_total = 1
    recorder.stop_recording()
    metadata = history_db.get_run_metadata(run_id)
    assert metadata is not None
    assert metadata.guided_phases == (
        RunGuidedPhase("sweep", 5.0, 25.0),
        RunGuidedPhase("hold", 25.0, 35.0),
        RunGuidedPhase("coast_down", 35.0, 43.0),
    )


def test_repeated_guided_steps_are_listed_once(make_logger) -> None:
    recorder = make_logger()
    recorder.start_recording()

    for phase in ("sweep", "hold", "sweep", "hold", None):
        recorder.mark_guided_phase(phase)

    assert recorder.status().guided_phases_completed == ("sweep", "hold")


def test_guided_phase_is_ignored_without_an_active_recording(make_logger) -> None:
    recorder = make_logger()

    status = recorder.mark_guided_phase("sweep")

    assert status.guided_phase is None
    assert recorder._recording_session.current_guided_phase() is None


def test_guided_phases_reset_with_each_new_run(make_logger) -> None:
    recorder = make_logger()
    first = recorder.start_recording().run_id
    assert recorder.mark_guided_phase("hold").guided_phase == "hold"
    assert recorder.mark_guided_phase("coast_down").guided_phases_completed == ("hold",)
    recorder.stop_recording()
    second = recorder.start_recording().run_id

    session = recorder._recording_session
    assert session.guided_phases_for_run(first) == ()
    assert session.guided_phases_for_run(second) == ()
    assert recorder.status().guided_phase is None
    assert recorder.status().guided_phases_completed == ()


def _brake_step_drive() -> list[tuple[float, float]]:
    """The guided brake step as the recorder stores it: 4 rows a second, GPS speed at 1 Hz.

    A lift-off coast (0.04 g), a gentle stop (0.14 g) and a dab on the brakes too
    short to judge (100 to 70 km/h in 3 s) first, then three firm stops from 100
    to 40 km/h in 6 s (0.28 g), each followed by speeding up again.
    """
    legs = [(4.0, 100.0, 100.0), (10.0, 100.0, 85.0), (4.0, 85.0, 100.0), (8.0, 100.0, 60.0)]
    legs += [(8.0, 60.0, 100.0), (3.0, 100.0, 70.0), (5.0, 70.0, 100.0)]
    for _stop in range(3):
        legs += [(4.0, 100.0, 100.0), (6.0, 100.0, 40.0), (6.0, 40.0, 100.0)]
    legs.append((4.0, 100.0, 100.0))

    def speed_at(t_s: float) -> float:
        for duration_s, start, end in legs:
            if t_s <= duration_s:
                return start + (end - start) * t_s / duration_s
            t_s -= duration_s
        return legs[-1][2]

    total_s = sum(duration_s for duration_s, _start, _end in legs)
    return [(tick / 4.0, speed_at(float(int(tick / 4.0)))) for tick in range(int(total_s * 4))]


def test_guided_brake_step_counts_the_stops_the_analysis_sees_as_braking(make_logger) -> None:
    recorder = make_logger()
    recorder.start_recording()
    session = recorder._recording_session
    drive = _brake_step_drive()
    start_s = 100.0

    # Braking outside the brake step is the analysis's business, not the step's.
    session.mark_guided_phase("hold")
    for t_s, speed in drive:
        session.observe_speed(t_s, speed)
    assert recorder.status().guided_brake_stops == 0

    session.mark_guided_phase("brake")
    seen: list[int] = []
    for t_s, speed in drive:
        session.observe_speed(start_s + t_s, speed)
        if not seen or seen[-1] != recorder.status().guided_brake_stops:
            seen.append(recorder.status().guided_brake_stops)

    # The coast, the gentle stop and the dab are not braking; each firm stop
    # counts once, the same stops the analysis's braking rule finds in the
    # whole series.
    assert seen == [0, 1, 2, 3]
    assert len(braking_intervals(drive, speed_slopes_kmh_s(drive))) == 3
    # Finishing the step keeps the count for the panel; a new run starts over.
    assert recorder.mark_guided_phase(None).guided_brake_stops == 3
    recorder.stop_recording()
    recorder.start_recording()
    assert recorder.status().guided_brake_stops == 0


_G_KMH_S = 9.80665 * 3.6


def _gps_ticks(legs: list[tuple[float, float, float]], *, fix_offset_s: float, seed: int):
    """*legs* as the recorder stores them from a 1 Hz GPS: 4 rows a second.

    Each fix reports the speed 0.8 s earlier and reaches the Pi 0-0.1 s after
    its second (*fix_offset_s* sets where the seconds fall between rows), so the
    staircase steps land on irregular rows, as on a Pi whose flush ticks are not
    locked to the GPS.
    """

    def speed_at(t_s: float) -> float:
        for duration_s, start, end in legs:
            if t_s <= duration_s:
                return start + (end - start) * t_s / duration_s
            t_s -= duration_s
        return legs[-1][2]

    rng = random.Random(seed)
    total_s = sum(duration_s for duration_s, _start, _end in legs)
    fixes = [
        (fix_offset_s + second + rng.uniform(0.0, 0.1), speed_at(max(0.0, second - 0.8)))
        for second in range(int(total_s) + 1)
    ]
    rows: list[tuple[float, float]] = []
    for tick in range(int(total_s * 4)):
        arrived = [speed for fix_s, speed in fixes if fix_s <= tick / 4.0]
        if arrived:
            rows.append((tick / 4.0, arrived[-1]))
    return rows


@pytest.mark.parametrize("firm_g", [0.2, 0.3])
@pytest.mark.parametrize("fix_offset_s", [i / 20 for i in range(20)])
def test_firm_stops_count_once_each_on_a_one_hz_gps(fix_offset_s: float, firm_g: float) -> None:
    """Stops from 100 to 40 km/h count once each on a 1 Hz GPS, from the step's gentlest 0.2 g.

    A slowdown at 0.1 g first does not count. The live count and the analysis
    find the same three stops.
    """
    firm_kmh_s = firm_g * _G_KMH_S
    # The brakes take half a second to bite and to let go (half the deceleration).
    bite_kmh = firm_kmh_s * 0.25
    slowdown_s = 60.0 / (0.1 * _G_KMH_S)
    legs = [(4.0, 100.0, 100.0), (slowdown_s, 100.0, 40.0), (8.0, 40.0, 100.0)]
    for _stop in range(3):
        legs += [
            (4.0, 100.0, 100.0),
            (0.5, 100.0, 100.0 - bite_kmh),
            ((60.0 - 2 * bite_kmh) / firm_kmh_s, 100.0 - bite_kmh, 40.0 + bite_kmh),
            (0.5, 40.0 + bite_kmh, 40.0),
            (8.0, 40.0, 100.0),
        ]
    legs.append((6.0, 100.0, 100.0))
    drive = _gps_ticks(legs, fix_offset_s=fix_offset_s, seed=round(fix_offset_s * 20))

    stops = GuidedBrakeStops()
    for t_s, speed in drive:
        stops.observe(t_s, speed)

    assert stops.count == 3
    assert len(braking_intervals(drive, speed_slopes_kmh_s(drive))) == 3
