from __future__ import annotations

from pathlib import Path

from vibesensor.use_cases.updates.wifi.wifi_diagnostics import parse_wifi_diagnostics


def _wifi_log_dir(tmp_path: Path) -> Path:
    log_dir = tmp_path / "wifi"
    log_dir.mkdir()
    return log_dir


class TestParseWifiDiagnostics:
    def test_no_log_dir(self, tmp_path) -> None:
        assert parse_wifi_diagnostics(str(tmp_path / "nonexistent")) == []

    def test_summary_failure(self, tmp_path) -> None:
        log_dir = _wifi_log_dir(tmp_path)
        (log_dir / "summary.txt").write_text("status=FAILED\nrc=22\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        assert [(issue.phase, issue.message, issue.detail) for issue in issues] == [
            ("diagnostics", "Hotspot summary reports failure", "status=FAILED"),
        ]

    def test_summary_timeout_case_insensitive(self, tmp_path) -> None:
        log_dir = _wifi_log_dir(tmp_path)
        (log_dir / "summary.txt").write_text("status=timeout\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        assert any("timeout" in (issue.detail or "").lower() for issue in issues)

    def test_summary_password_not_leaked(self, tmp_path) -> None:
        log_dir = _wifi_log_dir(tmp_path)
        (log_dir / "summary.txt").write_text("status=FAILED psk=hunter2\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        for issue in issues:
            assert "hunter2" not in (issue.detail or "")

    def test_hotspot_log_errors(self, tmp_path) -> None:
        log_dir = _wifi_log_dir(tmp_path)
        (log_dir / "hotspot.log").write_text(
            "2024-01-01 INFO normaline\n2024-01-01 ERROR something failed\n2024-01-01 INFO ok\n",
        )
        issues = parse_wifi_diagnostics(str(log_dir))
        assert [(issue.phase, issue.message, issue.detail) for issue in issues] == [
            ("diagnostics", "Hotspot log issue", "2024-01-01 ERROR something failed"),
        ]

    def test_password_not_leaked_in_diagnostics(self, tmp_path) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "hotspot.log").write_text("ERROR psk=hunter2 failed\n")
        issues = parse_wifi_diagnostics(str(log_dir))
        for issue in issues:
            assert "hunter2" not in issue.detail
            assert "hunter2" not in issue.message

    def test_read_errors_are_ignored(self, tmp_path, monkeypatch) -> None:
        log_dir = tmp_path / "wifi"
        log_dir.mkdir()
        (log_dir / "summary.txt").write_text("status=FAILED\n")

        def raise_oserror(*_args, **_kwargs) -> str:
            raise OSError("boom")

        monkeypatch.setattr(Path, "read_text", raise_oserror)
        assert parse_wifi_diagnostics(str(log_dir)) == []
