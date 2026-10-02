"""CLI regression tests for hotspot-config fallback behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vibesensor.cli.hotspot_config import main


def _run_cli(
    config_path: Path,
    *,
    monkeypatch,
    capsys,
) -> tuple[str, str]:
    monkeypatch.setattr(sys, "argv", ["vibesensor-hotspot-config", str(config_path)])
    main()
    captured = capsys.readouterr()
    return captured.out, captured.err


@pytest.mark.parametrize(
    ("config_text", "expected_warning"),
    [
        pytest.param("ap: [unterminated\n", "Failed to parse hotspot config", id="parse-error"),
        pytest.param("- item\n", "must contain a top-level mapping", id="top-level-list"),
        pytest.param("ap: disabled\n", "has a non-mapping 'ap' section", id="ap-not-mapping"),
    ],
)
def test_hotspot_config_cli_warns_and_falls_back_on_invalid_config(
    tmp_path: Path,
    monkeypatch,
    capsys,
    config_text: str,
    expected_warning: str,
) -> None:
    missing_path = tmp_path / "missing.yaml"
    defaults_out, defaults_err = _run_cli(missing_path, monkeypatch=monkeypatch, capsys=capsys)
    assert defaults_err == ""

    broken_path = tmp_path / "broken.yaml"
    broken_path.write_text(config_text, encoding="utf-8")

    broken_out, broken_err = _run_cli(broken_path, monkeypatch=monkeypatch, capsys=capsys)

    assert broken_out == defaults_out
    assert "WARNING:" in broken_err
    assert str(broken_path) in broken_err
    assert expected_warning in broken_err
    assert "using defaults" in broken_err


def test_hotspot_config_cli_exports_operator_credentials_and_fixed_network(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config_path = tmp_path / "config.yaml"
    # Legacy device configs may still carry removed keys such as ap.channel.
    config_path.write_text(
        "ap:\n  ssid: Workshop\n  psk: secret-psk\n  channel: 11\n",
        encoding="utf-8",
    )

    out, err = _run_cli(config_path, monkeypatch=monkeypatch, capsys=capsys)

    assert err == ""
    assert out.splitlines() == [
        "SSID='Workshop'",
        "PSK='secret-psk'",
        "IP='10.4.0.1/24'",
        "CHANNEL=7",
        "IFNAME='wlan0'",
        "CON_NAME='VibeSensor-AP'",
    ]
