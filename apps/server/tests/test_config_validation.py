"""Tests for processing config validation — zero/negative/invalid values.

Covers fix for GitHub issue #273: ProcessingConfig values like sample_rate_hz,
fft_n, etc. must reject zero and negative values to prevent division-by-zero
crashes downstream.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.config import ProcessingConfig, ServerConfig, UDPConfig, load_config


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# ProcessingConfig.__post_init__ direct tests
# ---------------------------------------------------------------------------


def _make_processing(**overrides: int | float | None) -> ProcessingConfig:
    """Return a ProcessingConfig with sensible defaults, applying *overrides*."""
    defaults = dict(
        sample_rate_hz=800,
        waveform_seconds=8,
        waveform_display_hz=120,
        ui_push_hz=10,
        ui_heavy_push_hz=4,
        fft_update_hz=4,
        fft_n=2048,
        spectrum_min_hz=5.0,
        spectrum_max_hz=200,
        client_ttl_seconds=120,
        accel_scale_g_per_lsb=None,
    )
    defaults.update(overrides)
    return ProcessingConfig(**defaults)  # type: ignore[arg-type]


class TestPositiveIntegerClamping:
    """Zero and negative values for positive-int fields are clamped to 1."""

    @pytest.mark.parametrize(
        "field",
        [
            "sample_rate_hz",
            "waveform_seconds",
            "waveform_display_hz",
            "ui_push_hz",
            "ui_heavy_push_hz",
            "fft_update_hz",
            "spectrum_max_hz",
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
            "waveform_display_hz",
            "ui_push_hz",
            "ui_heavy_push_hz",
            "fft_update_hz",
            "client_ttl_seconds",
        ],
    )
    def test_valid_positive_values_preserved(self, field: str) -> None:
        cfg = _make_processing(**{field: 42})
        assert getattr(cfg, field) == 42


class TestFftNValidation:
    """fft_n must be >= 16 and a power of 2."""

    def test_zero_fft_n_clamped(self) -> None:
        cfg = _make_processing(fft_n=0)
        assert cfg.fft_n >= 16

    def test_negative_fft_n_clamped(self) -> None:
        cfg = _make_processing(fft_n=-512)
        assert cfg.fft_n >= 16

    def test_small_fft_n_clamped_to_16(self) -> None:
        cfg = _make_processing(fft_n=4)
        assert cfg.fft_n == 16

    def test_non_power_of_2_rounded_up(self) -> None:
        cfg = _make_processing(fft_n=1000)
        assert cfg.fft_n == 1024
        # Must be a power of 2
        assert cfg.fft_n & (cfg.fft_n - 1) == 0

    def test_non_power_of_2_small(self) -> None:
        cfg = _make_processing(fft_n=17)
        assert cfg.fft_n == 32

    @pytest.mark.parametrize("n", [16, 64, 128, 256, 512, 1024, 2048, 4096])
    def test_valid_power_of_2_preserved(self, n: int) -> None:
        cfg = _make_processing(fft_n=n)
        assert cfg.fft_n == n


class TestSpectrumMaxHzNyquist:
    """spectrum_max_hz must be below Nyquist (sample_rate_hz / 2)."""

    def test_spectrum_max_at_nyquist_clamped(self) -> None:
        # Nyquist for 800 Hz = 400; spectrum_max_hz=400 should be clamped
        cfg = _make_processing(sample_rate_hz=800, spectrum_max_hz=400)
        assert cfg.spectrum_max_hz < 400

    def test_spectrum_max_above_nyquist_clamped(self) -> None:
        cfg = _make_processing(sample_rate_hz=800, spectrum_max_hz=500)
        assert cfg.spectrum_max_hz < 400

    def test_spectrum_max_below_nyquist_preserved(self) -> None:
        cfg = _make_processing(sample_rate_hz=800, spectrum_max_hz=200)
        assert cfg.spectrum_max_hz == 200


class TestSpectrumMinHz:
    """spectrum_min_hz validation."""

    def test_negative_spectrum_min_hz_clamped_to_zero(self) -> None:
        cfg = _make_processing(spectrum_min_hz=-5.0)
        assert cfg.spectrum_min_hz == 0.0

    def test_zero_spectrum_min_hz_preserved(self) -> None:
        cfg = _make_processing(spectrum_min_hz=0.0)
        assert cfg.spectrum_min_hz == 0.0

    def test_positive_spectrum_min_hz_preserved(self) -> None:
        cfg = _make_processing(spectrum_min_hz=5.0)
        assert cfg.spectrum_min_hz == 5.0

    def test_default_spectrum_min_hz(self) -> None:
        cfg = _make_processing()
        assert cfg.spectrum_min_hz == 5.0


class TestLoadConfigValidation:
    """load_config() integration: invalid YAML values are clamped."""

    def test_zero_sample_rate_clamped(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"sample_rate_hz": 0}})
        cfg = load_config(config_path)
        assert cfg.processing.sample_rate_hz >= 1

    def test_negative_fft_n_clamped(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"fft_n": -1}})
        cfg = load_config(config_path)
        assert cfg.processing.fft_n >= 16
        assert cfg.processing.fft_n & (cfg.processing.fft_n - 1) == 0

    def test_zero_waveform_seconds_clamped(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"waveform_seconds": 0}})
        cfg = load_config(config_path)
        assert cfg.processing.waveform_seconds >= 1

    def test_zero_fft_update_hz_clamped(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"fft_update_hz": 0}})
        cfg = load_config(config_path)
        assert cfg.processing.fft_update_hz >= 1

    def test_zero_ui_push_hz_clamped(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {"processing": {"ui_push_hz": 0}})
        cfg = load_config(config_path)
        assert cfg.processing.ui_push_hz >= 1

    def test_default_config_passes_validation(self, tmp_path: Path) -> None:
        """Empty override → defaults must all pass validation unchanged."""
        config_path = tmp_path / "config.yaml"
        _write_config(config_path, {})
        cfg = load_config(config_path)
        assert cfg.processing.sample_rate_hz == 800
        assert cfg.processing.fft_n == 2048
        assert cfg.processing.waveform_seconds == 8
        assert cfg.processing.spectrum_min_hz == 5.0
        assert cfg.processing.spectrum_max_hz == 200


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
        kwargs = dict(
            data_host="0.0.0.0",
            data_port=9000,
            control_host="0.0.0.0",
            control_port=9001,
            data_queue_maxsize=1024,
        )
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
