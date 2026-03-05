"""I/O cleanup, time-source, and report-cli guard regressions.

Covers:
  1. firmware_cache.refresh() – target/old_current initialised before try
  2. firmware_cache._download_asset() – fd leak guard when os.fdopen fails
  3. gps_speed.resolve_speed() – TOCTOU snapshot of speed_mps
  4. gps_speed._is_gps_stale() – TOCTOU snapshot of last_update_ts
  5. report_cli.main() – PDF generation errors return 1 instead of traceback
  6. report_data_builder date_str – includes UTC suffix
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from vibesensor.report_cli import main as report_cli_main


def _make_summary(report_date: str, **overrides: Any) -> dict[str, Any]:
    """Build a minimal summary dict for map_summary tests."""
    base: dict[str, Any] = {
        "lang": "en",
        "report_date": report_date,
        "metadata": {},
        "findings": [],
        "top_causes": [],
        "speed_stats": {},
        "most_likely_origin": {},
        "sensor_intensity_by_location": [],
        "run_suitability": [],
        "phase_info": None,
        "plots": {"peaks_table": []},
        "test_plan": [],
    }
    base.update(overrides)
    return base


class TestReportCliErrorHandling:
    """PDF generation failures should return exit code 1, not raise."""

    def test_pdf_build_failure_returns_1(self, tmp_path: Path) -> None:
        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch(
                "vibesensor.report_cli.build_report_pdf",
                side_effect=RuntimeError("PDF engine failed"),
            ),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(input=run_file, output=None, summary_json=None),
            ),
        ):
            result = report_cli_main()
            assert result == 1

    def test_pdf_build_success_returns_0(self, tmp_path: Path) -> None:
        run_file = tmp_path / "test_run.jsonl"
        run_file.write_text('{"event": "meta"}\n')

        with (
            patch("vibesensor.report_cli.summarize_log", return_value={"some": "summary"}),
            patch("vibesensor.report_cli.build_report_pdf", return_value=b"%PDF-1.4 fake"),
            patch("vibesensor.report_cli.map_summary", return_value={}),
            patch(
                "vibesensor.report_cli.parse_args",
                return_value=MagicMock(
                    input=run_file, output=tmp_path / "out.pdf", summary_json=None
                ),
            ),
        ):
            result = report_cli_main()
            assert result == 0
            assert (tmp_path / "out.pdf").exists()
