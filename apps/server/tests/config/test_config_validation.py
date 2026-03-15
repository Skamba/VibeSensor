"""Tests for processing config validation — zero/negative/invalid values.

Covers fix for GitHub issue #273: ProcessingConfig values like sample_rate_hz,
fft_n, etc. must reject zero and negative values to prevent division-by-zero
crashes downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.app.settings import LoggingConfig, ProcessingConfig, ServerConfig, UDPConfig, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# ProcessingConfig.__post_init__ direct tests
# ---------------------------------------------------------------------------


def _make_processing(**overrides: float | None) -> ProcessingConfig:
    """Return a ProcessingConfig with sensible defaults, applying *overrides*."""
    defaults: dict[str, float | None] = {
        "sample_rate_hz": 800,
        "waveform_seconds": 8,
        "client_ttl_seconds": 120,
        "accel_scale_g_per_lsb": None,
    }
    defaults.update(overrides)
    return ProcessingConfig(**defaults)  # type: ignore[arg-type]


class TestPositiveIntegerClamping:
    """Zero and negative values for positive-int fields are clamped to 1."""

    @pytest.mark.parametrize(
        "field",
        [
            "sample_rate_hz",
            "waveform_seconds",
            "client_ttl_seconds",
        ],
    )
    @pytest.mark.parametrize("bad_value", [0, -1, -100])
    def test_zero_and_negative_clamped_to_minimum(self, field: str, bad_value: int) -> None:
        cfg = _make_processing(**{field: bad_value})
        assert getattr(cfg, field) >= 1

    @pytest.mark.parametrize(
        "field",
        [
            "sample_rate_hz",
            "waveform_seconds",
            "client_ttl_seconds",
        ],
    )
    def test_valid_positive_values_preserved(self, field: str) -> None:
        cfg = _make_processing(**{field: 42})
        assert getattr(cfg, field) == 42


class TestLoadConfigValidation:
    """load_config() integration: invalid YAML values are clamped."""

    @pytest.mark.parametrize(
        "field",
        ["sample_rate_hz", "waveform_seconds"],
    )
    def test_zero_value_clamped_to_at_least_1(self, tmp_path: Path, field: str) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {field: 0}})
        cfg = load_config(config_path)
        assert getattr(cfg.processing, field) >= 1, f"{field} should be clamped to >= 1"

    def test_default_config_passes_validation(self, tmp_path: Path) -> None:
        """Empty override → defaults must all pass validation unchanged."""
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {})
        cfg = load_config(config_path)
        assert cfg.processing.sample_rate_hz == 800
        assert cfg.processing.waveform_seconds == 8


# ---------------------------------------------------------------------------
# ServerConfig.__post_init__ validation
# ---------------------------------------------------------------------------


class TestServerConfigValidation:
    """ServerConfig.port must be 1–65535."""

    def test_valid_port(self) -> None:
        cfg = ServerConfig(host="0.0.0.0", port=8000)
        assert cfg.port == 8000

    @pytest.mark.parametrize("bad_port", [0, -1, 65536, 100_000])
    def test_invalid_port_rejected(self, bad_port: int) -> None:
        with pytest.raises(ValueError, match="port"):
            ServerConfig(host="0.0.0.0", port=bad_port)

    def test_boundary_ports_accepted(self) -> None:
        assert ServerConfig(host="0.0.0.0", port=1).port == 1
        assert ServerConfig(host="0.0.0.0", port=65535).port == 65535


# ---------------------------------------------------------------------------
# UDPConfig.__post_init__ validation
# ---------------------------------------------------------------------------


class TestUDPConfigValidation:
    """UDPConfig port and queue size validation."""

    def test_valid_config(self) -> None:
        cfg = UDPConfig(
            data_host="0.0.0.0",
            data_port=9000,
            control_host="0.0.0.0",
            control_port=9001,
            data_queue_maxsize=1024,
        )
        assert cfg.data_port == 9000

    @pytest.mark.parametrize("field", ["data_port", "control_port"])
    @pytest.mark.parametrize("bad_value", [0, -1, 65536])
    def test_invalid_port_rejected(self, field: str, bad_value: int) -> None:
        kwargs = {
            "data_host": "0.0.0.0",
            "data_port": 9000,
            "control_host": "0.0.0.0",
            "control_port": 9001,
            "data_queue_maxsize": 1024,
        }
        kwargs[field] = bad_value
        with pytest.raises(ValueError, match=field):
            UDPConfig(**kwargs)

    @pytest.mark.parametrize("bad_value", [0, -1])
    def test_invalid_queue_maxsize_rejected(self, bad_value: int) -> None:
        with pytest.raises(ValueError, match="data_queue_maxsize"):
            UDPConfig(
                data_host="0.0.0.0",
                data_port=9000,
                control_host="0.0.0.0",
                control_port=9001,
                data_queue_maxsize=bad_value,
            )


# ---------------------------------------------------------------------------
# LoggingConfig.__post_init__ validation
# ---------------------------------------------------------------------------


class TestLoggingConfigValidation:
    """LoggingConfig clamping for numeric fields."""

    def _make(self, **overrides) -> LoggingConfig:
        defaults = {
            "log_metrics": True,
            "metrics_log_hz": 4,
            "no_data_timeout_s": 15.0,
            "sensor_model": "ADXL345",
            "history_db_path": Path("/tmp/history.db"),
            "persist_history_db": True,
            "shutdown_analysis_timeout_s": 30.0,
            "app_log_path": Path("/tmp/app.log"),
        }
        defaults.update(overrides)
        return LoggingConfig(**defaults)

    def test_valid_config(self) -> None:
        cfg = self._make()
        assert cfg.metrics_log_hz == 4
        assert cfg.no_data_timeout_s == 15.0

    def test_zero_metrics_log_hz_clamped(self) -> None:
        cfg = self._make(metrics_log_hz=0)
        assert cfg.metrics_log_hz >= 1

    def test_negative_no_data_timeout_clamped(self) -> None:
        cfg = self._make(no_data_timeout_s=-5.0)
        assert cfg.no_data_timeout_s >= 0

    def test_negative_shutdown_timeout_clamped(self) -> None:
        cfg = self._make(shutdown_analysis_timeout_s=-1.0)
        assert cfg.shutdown_analysis_timeout_s >= 0


# ---------------------------------------------------------------------------
# ProcessingConfig: buffer memory bound
# ---------------------------------------------------------------------------


class TestBufferMemoryBound:
    """sample_rate_hz × waveform_seconds exceeding 524288 clamps waveform_seconds."""

    def test_extreme_buffer_clamped(self) -> None:
        cfg = _make_processing(sample_rate_hz=50000, waveform_seconds=20)
        # 50000 × 20 = 1,000,000 > 524,288 → waveform_seconds should be clamped
        assert cfg.sample_rate_hz * cfg.waveform_seconds <= 524_288

    def test_normal_buffer_preserved(self) -> None:
        cfg = _make_processing(sample_rate_hz=800, waveform_seconds=8)
        # 800 × 8 = 6,400 — well within limit
        assert cfg.waveform_seconds == 8


# ---------------------------------------------------------------------------
# load_config: accel_scale_g_per_lsb validation
# ---------------------------------------------------------------------------


class TestAccelScaleValidation:
    """accel_scale_g_per_lsb ≤ 0 should be reset to None (auto-detection)."""

    def test_zero_accel_scale_reset(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"accel_scale_g_per_lsb": 0}})
        cfg = load_config(config_path)
        assert cfg.processing.accel_scale_g_per_lsb is None

    def test_negative_accel_scale_reset(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"accel_scale_g_per_lsb": -0.004}})
        cfg = load_config(config_path)
        assert cfg.processing.accel_scale_g_per_lsb is None

    def test_valid_accel_scale_preserved(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"accel_scale_g_per_lsb": 0.004}})
        cfg = load_config(config_path)
        assert cfg.processing.accel_scale_g_per_lsb == pytest.approx(0.004)
