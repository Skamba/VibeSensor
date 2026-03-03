"""Tests for the 10-item grumpy code quality review fixes.

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# Item 1 + 2: Public API naming in domain_models
# ---------------------------------------------------------------------------


class TestDomainModelsPublicAPI:
    """Verify that formerly-private helpers are importable by their public names."""

    def test_as_float_or_none_importable(self) -> None:
        from vibesensor.domain_models import as_float_or_none

        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None
        assert as_float_or_none("") is None
        assert as_float_or_none(float("nan")) is None
        assert as_float_or_none(float("inf")) is None

    def test_as_int_or_none_importable(self) -> None:
        from vibesensor.domain_models import as_int_or_none

        assert as_int_or_none(3.7) == 4
        assert as_int_or_none(None) is None

    def test_sanitize_aspects_importable(self) -> None:
        from vibesensor.domain_models import sanitize_aspects

        result = sanitize_aspects({"tire_width_mm": 225.0})
        assert "tire_width_mm" in result

    def test_new_car_id_importable(self) -> None:
        from vibesensor.domain_models import new_car_id

        car_id = new_car_id()
        assert isinstance(car_id, str) and len(car_id) > 0

    def test_backward_compat_aliases(self) -> None:
        """Old underscore-prefixed names still resolve."""
        from vibesensor.domain_models import (
            _as_float_or_none,
            _as_int_or_none,
            _new_car_id,
            _sanitize_aspects,
            as_float_or_none,
            as_int_or_none,
            new_car_id,
            sanitize_aspects,
        )

        assert _as_float_or_none is as_float_or_none
        assert _as_int_or_none is as_int_or_none
        assert _sanitize_aspects is sanitize_aspects
        assert _new_car_id is new_car_id

    def test_domain_models_has_all(self) -> None:
        import vibesensor.domain_models as dm

        assert hasattr(dm, "__all__")
        assert "as_float_or_none" in dm.__all__
        assert "CarConfig" in dm.__all__

    def test_runlog_re_exports(self) -> None:
        """runlog.as_float_or_none still works as before."""
        from vibesensor.runlog import as_float_or_none

        assert as_float_or_none(42) == 42.0


# ---------------------------------------------------------------------------
# Item 3: car_library import copy at module level
# ---------------------------------------------------------------------------


class TestCarLibraryImport:
    def test_copy_at_module_level(self) -> None:
        """copy should be importable from car_library's module scope."""
        import inspect

        import vibesensor.car_library as cl

        source = inspect.getsource(cl)
        # Must have top-level `import copy`, not inside a function
        lines = source.split("\n")
        # Find lines that are `import copy` at indentation level 0
        top_level_copy_import = any(
            line.strip() == "import copy" and not line.startswith(" ") for line in lines
        )
        assert top_level_copy_import, "import copy must be at module level"


# ---------------------------------------------------------------------------
# Item 4: build_order_bands lives in diagnostics_shared
# ---------------------------------------------------------------------------


class TestBuildOrderBandsLocation:
    def test_importable_from_diagnostics_shared(self) -> None:
        from vibesensor.diagnostics_shared import build_order_bands

        assert callable(build_order_bands)

    def test_not_in_runtime(self) -> None:
        """The old _build_order_bands should not exist in runtime anymore."""
        import vibesensor.runtime as rt

        assert not hasattr(rt, "_build_order_bands")

    def test_build_order_bands_basic(self) -> None:
        from vibesensor.diagnostics_shared import build_order_bands

        orders = {
            "wheel_hz": 10.0,
            "drive_hz": 30.0,
            "engine_hz": 60.0,
            "wheel_uncertainty_pct": 0.02,
            "drive_uncertainty_pct": 0.03,
            "engine_uncertainty_pct": 0.04,
        }
        settings = {}
        bands = build_order_bands(orders, settings)
        assert isinstance(bands, list)
        assert len(bands) >= 4  # wheel_1x, wheel_2x, drive/engine, engine_2x
        keys = [b["key"] for b in bands]
        assert "wheel_1x" in keys
        assert "wheel_2x" in keys
        assert "engine_2x" in keys


# ---------------------------------------------------------------------------
# Item 5: WorkerPool.submit() tracks timing
# ---------------------------------------------------------------------------


class TestWorkerPoolSubmitTiming:
    def test_submit_tracks_wait_time(self) -> None:
        from vibesensor.worker_pool import WorkerPool

        pool = WorkerPool(max_workers=2)
        try:
            # Submit a task that takes a measurable amount of time
            future = pool.submit(time.sleep, 0.05)
            future.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 1
            assert stats["total_wait_s"] >= 0.04  # at least ~50ms
        finally:
            pool.shutdown()

    def test_submit_timing_accumulates(self) -> None:
        from vibesensor.worker_pool import WorkerPool

        pool = WorkerPool(max_workers=2)
        try:
            futures = [pool.submit(time.sleep, 0.02) for _ in range(3)]
            for f in futures:
                f.result()
            stats = pool.stats()
            assert stats["total_tasks"] == 3
            assert stats["total_wait_s"] >= 0.05  # at least ~60ms total
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# Item 6: _sanitize_name truncation
# ---------------------------------------------------------------------------


class TestSanitizeName:
    def test_ascii_within_limit(self) -> None:
        from vibesensor.registry import _sanitize_name

        assert _sanitize_name("Hello") == "Hello"

    def test_truncation_at_32_bytes(self) -> None:
        from vibesensor.registry import _sanitize_name

        # 32 'A's → exactly 32 bytes → should pass through
        assert _sanitize_name("A" * 32) == "A" * 32
        # 33 'A's → truncated to 32
        assert _sanitize_name("A" * 33) == "A" * 32

    def test_multibyte_truncation(self) -> None:
        from vibesensor.registry import _sanitize_name

        # Each '€' is 3 UTF-8 bytes.  10 × 3 = 30 bytes → fits in 32.
        # 11 × 3 = 33 bytes → must truncate without splitting.
        name = "€" * 11
        result = _sanitize_name(name)
        assert len(result.encode("utf-8")) <= 32
        # Should have exactly 10 '€' chars (30 bytes), not a broken sequence
        assert result == "€" * 10

    def test_control_chars_stripped(self) -> None:
        from vibesensor.registry import _sanitize_name

        assert _sanitize_name("hel\x00lo") == "hello"
        assert _sanitize_name("\x01\x02\x03") == ""


# ---------------------------------------------------------------------------
# Item 7: severity_from_peak always returns dict
# ---------------------------------------------------------------------------


class TestSeverityFromPeakReturnType:
    def test_low_db_returns_dict(self) -> None:
        from vibesensor.diagnostics_shared import severity_from_peak

        result = severity_from_peak(vibration_strength_db=-100.0, sensor_count=0)
        assert isinstance(result, dict)
        assert "key" in result
        assert "db" in result
        assert "state" in result

    def test_high_db_returns_dict(self) -> None:
        from vibesensor.diagnostics_shared import severity_from_peak

        result = severity_from_peak(vibration_strength_db=50.0, sensor_count=1)
        assert isinstance(result, dict)

    def test_with_prior_state_returns_dict(self) -> None:
        from vibesensor.diagnostics_shared import severity_from_peak

        state = {"current_bucket": "l2", "pending_bucket": None}
        result = severity_from_peak(vibration_strength_db=5.0, sensor_count=1, prior_state=state)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Item 8: Nyquist uses float division
# ---------------------------------------------------------------------------


class TestNyquistFloatDivision:
    def test_odd_sample_rate_nyquist(self) -> None:
        from vibesensor.config import ProcessingConfig

        # With sample_rate_hz=801, Nyquist = 400.5 Hz.
        # spectrum_max_hz=400 should be valid (400 < 400.5).
        # With the old integer division: Nyquist = 400, so 400 >= 400 → clamped.
        # With float division: Nyquist = 400.5, so 400 < 400.5 → passes.
        cfg = ProcessingConfig(
            sample_rate_hz=801,
            waveform_seconds=8,
            waveform_display_hz=120,
            ui_push_hz=10,
            ui_heavy_push_hz=4,
            fft_update_hz=4,
            fft_n=2048,
            spectrum_min_hz=5.0,
            spectrum_max_hz=400,
            client_ttl_seconds=120,
            accel_scale_g_per_lsb=None,
        )
        assert cfg.spectrum_max_hz == 400  # NOT clamped to 399

    def test_even_sample_rate_still_clamps(self) -> None:
        from vibesensor.config import ProcessingConfig

        # With sample_rate_hz=800, Nyquist = 400.0 Hz.
        # spectrum_max_hz=400 should be clamped (400 >= 400).
        cfg = ProcessingConfig(
            sample_rate_hz=800,
            waveform_seconds=8,
            waveform_display_hz=120,
            ui_push_hz=10,
            ui_heavy_push_hz=4,
            fft_update_hz=4,
            fft_n=2048,
            spectrum_min_hz=5.0,
            spectrum_max_hz=400,
            client_ttl_seconds=120,
            accel_scale_g_per_lsb=None,
        )
        assert cfg.spectrum_max_hz == 399  # clamped


# ---------------------------------------------------------------------------
# Item 9: bounded_sample final trim
# ---------------------------------------------------------------------------


class TestBoundedSampleTrim:
    def test_never_exceeds_max_items(self) -> None:
        from vibesensor.runlog import bounded_sample

        # Test with various sizes to exercise edge cases
        for total in range(1, 30):
            for max_items in range(1, 10):
                samples = iter([{"v": i} for i in range(total)])
                kept, count, stride = bounded_sample(samples, max_items=max_items)
                assert len(kept) <= max_items, (
                    f"total={total}, max_items={max_items}: got {len(kept)} items"
                )
                assert count == total

    def test_max_items_1_edge_case(self) -> None:
        from vibesensor.runlog import bounded_sample

        samples = iter([{"v": i} for i in range(5)])
        kept, count, stride = bounded_sample(samples, max_items=1)
        assert len(kept) <= 1
        assert count == 5


# ---------------------------------------------------------------------------
# Item 10: __all__ on key modules
# ---------------------------------------------------------------------------


class TestModuleAllExports:
    @pytest.mark.parametrize(
        "module_path",
        [
            "vibesensor.domain_models",
            "vibesensor.protocol",
            "vibesensor.worker_pool",
            "vibesensor.car_library",
            "vibesensor.gps_speed",
            "vibesensor.registry",
        ],
    )
    def test_module_has_all(self, module_path: str) -> None:
        import importlib

        mod = importlib.import_module(module_path)
        assert hasattr(mod, "__all__"), f"{module_path} is missing __all__"
        assert len(mod.__all__) > 0, f"{module_path}.__all__ is empty"
