"""Tests for the report CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from vibesensor.report_cli import main


def test_main_missing_input_file(tmp_path: Path, capsys: object) -> None:
    """CLI must return 1 and print an error when the input file does not exist."""
    fake_input = tmp_path / "does_not_exist.jsonl"
    with patch("sys.argv", ["vibesensor-report", str(fake_input)]):
        code = main()
    assert code == 1


def test_main_invalid_json(tmp_path: Path) -> None:
    """CLI must return 1 when the input file contains invalid JSON."""
    bad_file = tmp_path / "bad.jsonl"
    bad_file.write_text("not valid json\n")
    with patch("sys.argv", ["vibesensor-report", str(bad_file)]):
        code = main()
    assert code == 1
