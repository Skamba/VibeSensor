"""CLI coverage for config preflight defaults, argument errors, and JSON output."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from vibesensor.app.config_loader import load_config
from vibesensor.cli import preflight


def test_preflight_cli_dump_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight", "--dump-defaults"])

    assert preflight.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["server"]["port"] == 80
    assert payload["processing"]["sample_rate_hz"] == 800


def test_preflight_cli_requires_config_without_dump_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight"])

    with pytest.raises(SystemExit):
        preflight.main()


def test_preflight_cli_rejects_dump_defaults_with_config(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["vibesensor-config-preflight", "--dump-defaults", "apps/server/config.dev.yaml"],
    )

    with pytest.raises(SystemExit):
        preflight.main()


def test_preflight_cli_prints_resolved_config(monkeypatch, capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("server:\n  port: 8000\n", encoding="utf-8")
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    monkeypatch.setenv("VIBESENSOR_WS_DEBUG", "1")
    monkeypatch.setenv("VIBESENSOR_REPO_PATH", str(tmp_path / "repo"))
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight", str(config_path)])

    assert preflight.main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["config_path"] == str(config_path.resolve())
    assert payload["server"]["port"] == 8000
    assert payload["process_settings"]["serve_static"] is False
    assert payload["process_settings"]["ws_debug"] is True
    assert payload["process_settings"]["repo_path"] == str(tmp_path / "repo")
    assert payload["process_settings"]["github_token_configured"] is True


def test_writable_path_checks_include_active_runtime_targets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            (
                "tracing:",
                "  enabled: true",
                "  output_path: traces/export.jsonl",
                "update:",
                f"  rollback_dir: {tmp_path / 'rollback'}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBESENSOR_UPDATE_STATE_PATH", str(tmp_path / "update" / "state.json"))
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_CACHE_DIR", str(tmp_path / "firmware"))

    cfg = load_config(config_path)

    assert [check.label for check in preflight._writable_path_checks(cfg)] == [
        "logging.history_db_path",
        "logging.app_log_path",
        "ap.self_heal.state_file",
        "tracing.output_path",
        "update.rollback_dir",
        "process_settings.update_state_path",
        "process_settings.firmware_cache_dir",
    ]


def test_preflight_cli_reports_unwritable_runtime_path(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    blocked_dir = tmp_path / "blocked"
    blocked_dir.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            (
                "logging:",
                "  history_db_path: blocked/history.db",
                "update:",
                f"  rollback_dir: {tmp_path / 'rollback'}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBESENSOR_UPDATE_STATE_PATH", str(tmp_path / "update" / "state.json"))
    monkeypatch.setenv("VIBESENSOR_FIRMWARE_CACHE_DIR", str(tmp_path / "firmware"))

    real_access = os.access

    def _mock_access(path: str | os.PathLike[str], mode: int) -> bool:
        if Path(path) == blocked_dir:
            return False
        return real_access(path, mode)

    monkeypatch.setattr(preflight.os, "access", _mock_access)
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight", str(config_path)])

    assert preflight.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "logging.history_db_path is not writable" in captured.err
    assert str(blocked_dir) in captured.err
