"""Cross-cutting review guardrail regressions (core set).

Each test group validates one of the hate-list items to prevent regression.
"""

from __future__ import annotations

from vibesensor.registry import _sanitize_name

_PROCESSING_DEFAULTS = dict(
    waveform_seconds=8,
    waveform_display_hz=120,
    ui_push_hz=10,
    ui_heavy_push_hz=4,
    fft_update_hz=4,
    fft_n=2048,
    spectrum_min_hz=5.0,
    client_ttl_seconds=120,
    accel_scale_g_per_lsb=None,
)


class TestSanitizeName:
    def test_ascii_within_limit(self) -> None:
        assert _sanitize_name("Hello") == "Hello"

    def test_truncation_at_32_bytes(self) -> None:
        assert _sanitize_name("A" * 32) == "A" * 32
        assert _sanitize_name("A" * 33) == "A" * 32

    def test_multibyte_truncation(self) -> None:
        # Each '€' is 3 UTF-8 bytes.  10 × 3 = 30 bytes → fits in 32.
        # 11 × 3 = 33 bytes → must truncate without splitting.
        name = "€" * 11
        result = _sanitize_name(name)
        assert len(result.encode("utf-8")) <= 32
        assert result == "€" * 10

    def test_control_chars_stripped(self) -> None:
        assert _sanitize_name("hel\x00lo") == "hello"
        assert _sanitize_name("\x01\x02\x03") == ""
