"""Tests for LifecycleManager._validate_startup() disk-check branches (8H)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from vibesensor.infra.runtime.health_state import RuntimeHealthState
from vibesensor.infra.runtime.lifecycle import LifecycleManager

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


def _make_lifecycle(db_path: str | None) -> tuple[LifecycleManager, RuntimeHealthState]:
    """Build a minimal LifecycleManager with a configurable db_path."""
    health_state = RuntimeHealthState()
    health_state.mark_ready()

    logging_cfg = SimpleNamespace(history_db_path=db_path)
    config = SimpleNamespace(logging=logging_cfg)

    runtime = MagicMock()
    runtime.config = config
    runtime.health_state = health_state

    lifecycle = LifecycleManager(runtime=runtime)
    return lifecycle, health_state


# ---------------------------------------------------------------------------
# _validate_startup tests
# ---------------------------------------------------------------------------


class TestValidateStartupDiskCheck:
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
