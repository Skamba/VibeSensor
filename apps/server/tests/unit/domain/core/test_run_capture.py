"""Tests for RunCapture domain object."""

from __future__ import annotations

import pytest

from vibesensor.domain import RunCapture, RunSetup


class TestRunCaptureConstruction:
    def test_minimal(self) -> None:
        rc = RunCapture(run_id="abc-123")
        assert rc.run_id == "abc-123"
        assert rc.setup == RunSetup()
        assert rc.analysis_settings == ()
        assert rc.measurements == ()
        assert rc.sample_count == 0
        assert rc.duration_s == 0.0

    def test_empty_run_id_raises(self) -> None:
        with pytest.raises(ValueError, match="run_id"):
            RunCapture(run_id="")

    def test_with_setup(self) -> None:
        setup = RunSetup(sensors=("acc1",))
        rc = RunCapture(run_id="r1", setup=setup)
        assert rc.setup.sensors == ("acc1",)

    def test_immutable(self) -> None:
        rc = RunCapture(run_id="r1")
        with pytest.raises(AttributeError):
            rc.run_id = "changed"  # type: ignore[misc]

    def test_analysis_settings_tuple(self) -> None:
        settings = (("floor_g", 0.002), ("enabled", True))
        rc = RunCapture(run_id="r1", analysis_settings=settings)
        assert rc.analysis_settings == settings
