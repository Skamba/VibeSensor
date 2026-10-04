from __future__ import annotations

from vibesensor.updates.runner import sanitize_log_line as sanitize_log_line


class TestSanitizeLogLine:
    def test_sanitizes_password(self) -> None:
        result = sanitize_log_line("psk=mysecretpassword123")
        assert "mysecretpassword123" not in result
        assert "psk=***" in result

    def test_sanitizes_key(self) -> None:
        result = sanitize_log_line("key: verysecret")
        assert "verysecret" not in result

    def test_truncates_long_lines(self) -> None:
        assert len(sanitize_log_line("x" * 1000)) <= 500

    def test_normal_line_unchanged(self) -> None:
        line = "Hotspot restored on attempt 1"
        assert sanitize_log_line(line) == line
