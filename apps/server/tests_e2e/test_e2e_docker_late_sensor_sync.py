"""Docker E2E: sensors that connect and clock-sync after recording started stay raw-backed."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import _cleanup_run, _simulate, _wait_complete
from tests_e2e.e2e_helpers import ANALYZABLE_SIM_DURATION_S, api_json, remove_all_clients

pytestmark = pytest.mark.e2e

# Sensors are synced at their HELLO, but one whose HELLO exchange is lost waits for
# the 2 s broadcast (processing_loop.CLOCK_SYNC_INTERVAL_S) and streams on its bare
# device clock meanwhile; leave room for that.
_PRE_SYNC_S = 4.0


def test_sensors_syncing_after_recording_start_are_replayed_from_raw_capture_e2e(
    e2e_env: dict[str, str],
) -> None:
    base = e2e_env["base_url"]
    remove_all_clients(base)
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        _simulate(
            e2e_env,
            duration=_PRE_SYNC_S + 2 * ANALYZABLE_SIM_DURATION_S,
            count=2,
            names="front-left,rear-left",
        )
        api_json(base, "/api/recording/stop", method="POST")
        run = _wait_complete(base, run_id)
        assert run["status"] == "complete"

        metadata = api_json(base, f"/api/history/{run_id}")["analysis"]["analysis_metadata"]
        # The pre-sync chunks were dropped and each sensor's raw capture starts at its
        # first synced chunk, so post-sync windows replay from raw capture instead of
        # silently falling back to the stored summary rows.
        assert metadata["raw_capture_mode"] in {"raw_backed", "partial_raw_backed"}
        assert metadata["raw_backed_sample_count"] > 0
        assert metadata["raw_replay_complete_window_count"] > 0
        assert metadata["raw_replay_sample_rate_unverified_sensor_count"] == 0
        assert metadata["raw_replay_timing_fallback_count"] == 0
        assert "legacy_summary_only" not in (metadata.get("fallback_reasons") or [])
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        _cleanup_run(base, run_id)
        remove_all_clients(base)
