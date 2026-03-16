"""Tests for the report CLI entry point."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from vibesensor.cli.report import main


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="missing_input_file"),
        pytest.param("not valid json\n", id="invalid_json"),
    ],
)
def test_main_returns_error(tmp_path: Path, content: str | None) -> None:
    """CLI must return 1 for missing or malformed input files."""
    input_file = tmp_path / "input.jsonl"
    if content is not None:
        input_file.write_text(content)
    with patch("sys.argv", ["vibesensor-report", str(input_file)]):
        assert main() == 1
