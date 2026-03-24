from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from vibesensor.cli.preflight import main


def test_preflight_cli_dump_defaults(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight", "--dump-defaults"])

    assert main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["server"]["port"] == 80
    assert payload["processing"]["sample_rate_hz"] == 800


def test_preflight_cli_requires_config_without_dump_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight"])

    with pytest.raises(SystemExit):
        main()


def test_preflight_cli_rejects_dump_defaults_with_config(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["vibesensor-config-preflight", "--dump-defaults", "apps/server/config.dev.yaml"],
    )

    with pytest.raises(SystemExit):
        main()


def test_preflight_cli_prints_resolved_config(monkeypatch, capsys, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("server:\n  port: 8000\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["vibesensor-config-preflight", str(config_path)])

    assert main() == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert captured.err == ""
    assert payload["config_path"] == str(config_path.resolve())
    assert payload["server"]["port"] == 8000
