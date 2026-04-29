"""Disk-check coverage for ``LifecycleManager._validate_startup()``.

This file intentionally exercises the private startup-validation helper because
the low-disk warning branches have no narrower public seam than booting the
full lifecycle manager. #3394 keeps this as the one justified private-method
test in the runtime lifecycle cluster.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, patch

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.lifecycle import LifecycleManager, LifecycleRuntime
from vibesensor.shared.ingest_diagnostics import IngestDiagnosticsCollector

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


def _make_lifecycle(db_path: str | None) -> tuple[LifecycleManager, RuntimeHealthState]:
    """Build a minimal LifecycleManager with a configurable db_path."""
    health_state = RuntimeHealthState()
    health_state.mark_ready()

    runtime = LifecycleRuntime(
        health_state=health_state,
        history_db_path=db_path,
        udp_data_host="0.0.0.0",
        udp_data_port=9000,
        udp_data_queue_maxsize=64,
        gpsd_host="127.0.0.1",
        gpsd_port=2947,
        shutdown_analysis_timeout_s=5.0,
        registry=MagicMock(),
        processor=MagicMock(),
        ingest_diagnostics=IngestDiagnosticsCollector(),
        control_plane=MagicMock(),
        processing_loop=MagicMock(),
        ws_hub=MagicMock(),
        ws_broadcast=MagicMock(),
        run_recorder=MagicMock(),
        gps_monitor=MagicMock(),
        obd_runner=MagicMock(),
        update_manager=MagicMock(job_task=None),
        esp_flash_manager=MagicMock(job_task=None),
        worker_pool=MagicMock(),
        history_db=MagicMock(aclose=AsyncMock()),
    )

    lifecycle = LifecycleManager(runtime=runtime, start_udp_receiver=MagicMock())
    return lifecycle, health_state


# ---------------------------------------------------------------------------
# _validate_startup tests
# ---------------------------------------------------------------------------


class TestValidateStartupDiskCheck:
    """Exercise low-disk warnings and startup skip branches around the history DB path."""

    def test_low_disk_appends_warning(self, tmp_path: Path) -> None:
        """Free space below threshold appends a warning to startup_warnings."""
        db_path = str(tmp_path / "vibesensor.db")
        lifecycle, health_state = _make_lifecycle(db_path)

        # 50 MB free — below 100 MB threshold
        low_usage = MagicMock()
        low_usage.free = 50 * 1024 * 1024

        with patch("shutil.disk_usage", return_value=low_usage):
            lifecycle._validate_startup()

        assert len(health_state.startup_warnings) == 1
        assert "low disk" in health_state.startup_warnings[0]

    def test_sufficient_disk_no_warning(self, tmp_path: Path) -> None:
        """Free space at or above threshold adds no warning."""
        db_path = str(tmp_path / "vibesensor.db")
        lifecycle, health_state = _make_lifecycle(db_path)

        enough_usage = MagicMock()
        enough_usage.free = 500 * 1024 * 1024

        with patch("shutil.disk_usage", return_value=enough_usage):
            lifecycle._validate_startup()

        assert health_state.startup_warnings == []

    def test_os_error_is_silent(self, tmp_path: Path) -> None:
        """OSError from disk_usage is silently swallowed — no warning, no exception."""
        db_path = str(tmp_path / "vibesensor.db")
        lifecycle, health_state = _make_lifecycle(db_path)

        with patch("shutil.disk_usage", side_effect=OSError("disk unavailable")):
            lifecycle._validate_startup()  # must not raise

        assert health_state.startup_warnings == []

    def test_memory_db_skips_check(self) -> None:
        """':memory:' as db_path skips the disk check entirely."""
        lifecycle, health_state = _make_lifecycle(":memory:")

        with patch("shutil.disk_usage") as mock_usage:
            lifecycle._validate_startup()

        mock_usage.assert_not_called()
        assert health_state.startup_warnings == []

    def test_none_db_path_skips_check(self) -> None:
        """None db_path skips the disk check entirely."""
        lifecycle, health_state = _make_lifecycle(None)

        with patch("shutil.disk_usage") as mock_usage:
            lifecycle._validate_startup()

        mock_usage.assert_not_called()
        assert health_state.startup_warnings == []


def test_lifecycle_manager_uses_lifecycle_owned_runtime_contract() -> None:
    import vibesensor.infra.runtime.lifecycle as lifecycle_module

    hints = get_type_hints(
        LifecycleManager.__init__,
        globalns=vars(lifecycle_module),
    )

    assert hints["runtime"] is lifecycle_module.LifecycleRuntime
