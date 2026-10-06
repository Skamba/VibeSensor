from __future__ import annotations

from test_support.core import TEST_CAR_ASPECTS

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.recording.lifecycle_state import RunLifecycleState


def _analysis_settings_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**TEST_CAR_ASPECTS)


def test_start_new_run_enables_state_and_returns_snapshot() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)

    snapshot = state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=12.5,
        current_total=7,
    )

    assert snapshot.run_id == "run-1"
    assert snapshot.start_time_utc == "2026-01-01T00:00:00Z"
    assert snapshot.start_mono_s == 12.5
    assert state.enabled is True
    assert state.run_id == "run-1"
    assert state.last_data_progress_mono_s == 12.5


def test_pending_flush_snapshot_depends_on_history_creation_and_progress() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=1.0,
        current_total=10,
    )

    assert state.pending_flush_snapshot(current_total=10, history_run_created=False) is None
    assert state.pending_flush_snapshot(current_total=11, history_run_created=False) is not None

    state.refresh_data_progress(now_mono_s=2.0, current_total=11)
    assert state.pending_flush_snapshot(current_total=11, history_run_created=True) is None
    assert state.pending_flush_snapshot(current_total=12, history_run_created=True) is not None


def test_auto_stop_reason_uses_last_data_progress_timestamp() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=10.0,
        current_total=0,
    )

    assert state.auto_stop_reason(now_mono_s=14.9) is None
    assert state.auto_stop_reason(now_mono_s=15.0) == "no_data_timeout"


def test_auto_stop_reason_caps_recording_duration_at_thirty_minutes() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=10.0,
        current_total=0,
    )
    state.mark_rows_written(now_mono_s=10.0 + 30 * 60 - 1.0)

    assert state.auto_stop_reason(now_mono_s=10.0 + 30 * 60 - 0.5) is None
    assert state.auto_stop_reason(now_mono_s=10.0 + 30 * 60) == "max_duration"


def test_stop_records_reason_until_the_next_run_starts() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=10.0,
        current_total=0,
    )

    state.stop(reason="max_duration")
    assert state.last_stop_reason == "max_duration"

    state.start_new_run(
        run_id="run-2",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:31:00Z",
        start_mono_s=2_000.0,
        current_total=0,
    )
    assert state.last_stop_reason is None


def test_stop_clears_active_run_state() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=3.0,
        current_total=4,
    )

    state.stop(reason="manual")

    assert state.enabled is False
    assert state.run_id is None
    assert state.start_time_utc is None
    assert state.start_mono_s is None
    assert state.last_data_progress_mono_s is None
    assert state.start_frames_total == 0
    assert state.last_active_frames_total == 0


def test_a_silent_sensor_counts_toward_the_stop_even_when_it_leaves_the_live_set() -> None:
    """Frames that vanish from the total (sensor no longer live) are not new data."""
    state = RunLifecycleState(no_data_timeout_s=60.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=0.0,
        current_total=100,
    )
    state.refresh_data_progress(now_mono_s=1.0, current_total=110)
    assert state.seconds_without_data(now_mono_s=1.0) == 0.0

    # Ten seconds later the registry no longer counts the silent sensor as live.
    state.refresh_data_progress(now_mono_s=11.0, current_total=0)
    assert state.seconds_without_data(now_mono_s=30.0) == 29.0
    assert state.auto_stop_reason(now_mono_s=60.9) is None
    assert state.auto_stop_reason(now_mono_s=61.0) == "no_data_timeout"

    # The sensor reconnects inside the grace period: recording carries on.
    state.refresh_data_progress(now_mono_s=45.0, current_total=120)
    assert state.seconds_without_data(now_mono_s=45.0) == 0.0
    assert state.auto_stop_reason(now_mono_s=61.0) is None

    state.stop(reason="manual")
    assert state.seconds_without_data(now_mono_s=50.0) is None
