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


def test_main_writes_pdf_and_optional_summary_json(tmp_path: Path) -> None:
    input_file = tmp_path / "input.jsonl"
    output_file = tmp_path / "out" / "report.pdf"
    summary_file = tmp_path / "out" / "summary.json"
    input_file.write_text('{"record_type":"metadata"}\n', encoding="utf-8")
    summary = {"run_id": "run-1", "rows": 1}

    with (
        patch(
            "sys.argv",
            [
                "vibesensor-report",
                str(input_file),
                "--output",
                str(output_file),
                "--summary-json",
                str(summary_file),
            ],
        ),
        patch("vibesensor.cli.report.summarize_log", return_value=summary) as summarize_log,
        patch("vibesensor.cli.report.prepare_report_input", return_value=object()),
        patch("vibesensor.cli.report.build_prepared_report_pdf", return_value=b"%PDF-test"),
    ):
        assert main() == 0

    summarize_log.assert_called_once_with(input_file, include_samples=True)
    assert output_file.read_bytes() == b"%PDF-test"
    assert summary_file.read_text(encoding="utf-8").startswith('{\n  "run_id": "run-1"')
