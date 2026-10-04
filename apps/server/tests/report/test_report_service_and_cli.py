"""Stored-run report delivery: the history service (cached, per language) and the CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_support.analysis import run_analysis
from test_support.core import ALL_WHEEL_SENSORS
from test_support.history_db_lifecycle import (
    build_history_db,
    create_analyzing_run,
    create_completed_run,
)
from test_support.pdf import extract_pdf_text
from test_support.synthetic_samples import make_fault_samples

from vibesensor.cli.report import main
from vibesensor.common.exceptions import AnalysisNotReadyError
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.service import HistoryReportService
from vibesensor.report.view_model import ReportView


def _stored_db(tmp_path: Path) -> Path:
    db = build_history_db(tmp_path)
    analysis = run_analysis(
        make_fault_samples(fault_sensor="front-left", sensors=ALL_WHEEL_SENSORS)
    )
    analysis["run_id"] = "run-1"
    create_completed_run(db, "run-1", analysis=analysis)
    create_analyzing_run(db, "run-busy")
    db.close()
    return tmp_path / "history.db"


@pytest.mark.asyncio
async def test_service_renders_requested_language_and_caches_per_language(tmp_path: Path) -> None:
    db = build_history_db(_stored_db(tmp_path).parent)
    rendered: list[str] = []

    def renderer(view: ReportView) -> bytes:
        rendered.append(view.lang)
        return render_report_pdf(view)

    service = HistoryReportService(db, pdf_renderer=renderer)
    try:
        nl = await service.build_pdf("run-1", "nl")
        again = await service.build_pdf("run-1", "nl")
        en = await service.build_pdf("run-1", "en")
        with pytest.raises(AnalysisNotReadyError):
            await service.build_pdf("run-busy", "en")
    finally:
        db.close()

    assert rendered == ["nl", "en"]
    assert nl.content == again.content
    assert nl.filename == "run-1_report.pdf"
    assert "Waarschijnlijke oorzaak" in extract_pdf_text(nl.content)
    assert "Likely cause" in extract_pdf_text(en.content)


def test_cli_renders_a_stored_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = _stored_db(tmp_path)
    out = tmp_path / "out" / "report.pdf"

    assert main([str(db_path), "run-1", "--lang", "nl", "--output", str(out)]) == 0

    assert "wrote report" in capsys.readouterr().out
    assert "Voor de werkplaats" in extract_pdf_text(out.read_bytes())


@pytest.mark.parametrize(
    ("run_id", "message"),
    [("missing", "not found"), ("run-busy", "still in progress")],
)
def test_cli_reports_unknown_or_unfinished_runs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    run_id: str,
    message: str,
) -> None:
    db_path = _stored_db(tmp_path)

    assert main([str(db_path), run_id]) == 1
    assert message in capsys.readouterr().err


def test_cli_rejects_a_missing_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "nope.db"), "run-1"]) == 1
    assert "history database not found" in capsys.readouterr().err
