from __future__ import annotations

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.use_cases.run.lifecycle_state import RunLifecycleState


def _analysis_settings_snapshot() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS)


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


def test_should_auto_stop_uses_last_data_progress_timestamp() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=10.0,
        current_total=0,
    )

    assert state.should_auto_stop(now_mono_s=14.9) is False
    assert state.should_auto_stop(now_mono_s=15.0) is True


def test_stop_clears_active_run_state() -> None:
    state = RunLifecycleState(no_data_timeout_s=5.0)
    state.start_new_run(
        run_id="run-1",
        analysis_settings_snapshot=_analysis_settings_snapshot(),
        start_time_utc="2026-01-01T00:00:00Z",
        start_mono_s=3.0,
        current_total=4,
    )

    state.stop()

    assert state.enabled is False
    assert state.run_id is None
    assert state.start_time_utc is None
    assert state.start_mono_s is None
    assert state.last_data_progress_mono_s is None
    assert state.start_frames_total == 0
    assert state.last_active_frames_total == 0
