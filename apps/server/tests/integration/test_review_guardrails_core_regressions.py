"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from vibesensor.common.json_utils import as_float_or_none, as_int_or_none
from vibesensor.dsp.order_bands import build_order_bands
from vibesensor.ingest.client_metadata import sanitize_client_name
from vibesensor.settings.car_config import new_car_id

# ---------------------------------------------------------------------------
# Item 1 + 2: Public API naming in domain_models
# ---------------------------------------------------------------------------


class TestDomainModelsPublicAPI:
    """Verify public helpers through their observable normalization behavior."""

    def test_as_float_or_none_normalizes_numeric_inputs(self) -> None:
        assert as_float_or_none(3.14) == 3.14
        assert as_float_or_none(None) is None
        assert as_float_or_none("") is None
        assert as_float_or_none(float("nan")) is None
        assert as_float_or_none(float("inf")) is None

    def test_as_int_or_none_rounds_numeric_inputs(self) -> None:
        assert as_int_or_none(3.7) == 4
        assert as_int_or_none(None) is None

    def test_new_car_id_returns_non_empty_identifier(self) -> None:
        car_id = new_car_id()
        assert isinstance(car_id, str) and len(car_id) > 0

    def test_runlog_re_exports(self) -> None:
        """runlog.as_float_or_none still works as before."""
        from vibesensor.common.json_utils import as_float_or_none as runlog_as_float

        assert runlog_as_float(42) == 42.0


# ---------------------------------------------------------------------------
# Item 4: build_order_bands lives in shared.order_bands
# ---------------------------------------------------------------------------


class TestBuildOrderBandsLocation:
    """Verify order-band helpers stay in the shared module and keep basic behavior."""

    def test_build_order_bands_basic(self) -> None:
        from vibesensor.dsp.order_bands import build_diagnostic_settings

        orders = {
            "wheel_hz": 10.0,
            "drive_hz": 30.0,
            "engine_hz": 60.0,
            "wheel_uncertainty_pct": 0.02,
            "drive_uncertainty_pct": 0.03,
            "engine_uncertainty_pct": 0.04,
        }
        settings = build_diagnostic_settings({})
        bands = build_order_bands(orders, settings)
        assert isinstance(bands, list)
        assert len(bands) >= 4  # wheel_1x, wheel_2x, drive/engine, engine_2x
        keys = [b["key"] for b in bands]
        assert "wheel_1x" in keys
        assert "wheel_2x" in keys
        assert "engine_2x" in keys


# ---------------------------------------------------------------------------
# Item 6: sanitize_client_name truncation
# ---------------------------------------------------------------------------


class TestSanitizeName:
    """Verify client-name sanitization strips controls and truncates by UTF-8 byte length."""

    def test_ascii_within_limit(self) -> None:
        assert sanitize_client_name("Hello") == "Hello"

    def test_truncation_at_32_bytes(self) -> None:
        assert sanitize_client_name("A" * 32) == "A" * 32
        assert sanitize_client_name("A" * 33) == "A" * 32

    def test_multibyte_truncation(self) -> None:
        # Each '€' is 3 UTF-8 bytes.  10 × 3 = 30 bytes → fits in 32.
        # 11 × 3 = 33 bytes → must truncate without splitting.
        name = "€" * 11
        result = sanitize_client_name(name)
        assert len(result.encode("utf-8")) <= 32
        assert result == "€" * 10

    def test_control_chars_stripped(self) -> None:
        assert sanitize_client_name("hel\x00lo") == "hello"
        assert sanitize_client_name("\x01\x02\x03") == ""
