"""``vibesensor-report`` CLI: render the PDF report of a run stored in a history DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vibesensor.common.exceptions import AnalysisNotReadyError
from vibesensor.common.filenames import safe_filename
from vibesensor.history.helpers import require_analysis_ready
from vibesensor.history.history_db import HistoryDB
from vibesensor.report.i18n import normalize_lang
from vibesensor.report.pdf import render_report_pdf
from vibesensor.report.view_model import build_report_view


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the report CLI."""
    parser = argparse.ArgumentParser(
        description="Render the VibeSensor PDF report of a stored run",
    )
    parser.add_argument("db", type=Path, help="History database (history.db)")
    parser.add_argument("run_id", help="Run id to report on")
    parser.add_argument("--lang", choices=("en", "nl"), default=None, help="Report language")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: <run_id>_report.pdf in the current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``vibesensor-report`` CLI tool."""
    args = parse_args(argv)
    if not args.db.is_file():
        print(f"Error: history database not found: {args.db}", file=sys.stderr)
        return 1
    db = HistoryDB(args.db)
    try:
        run = db.get_run(args.run_id)
    finally:
        db.close()
    if run is None:
        print(f"Error: run {args.run_id!r} not found in {args.db}", file=sys.stderr)
        return 1
    try:
        analysis = require_analysis_ready(run)
    except AnalysisNotReadyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    lang = normalize_lang(args.lang or analysis.language or run.metadata.language)
    pdf = render_report_pdf(build_report_view(analysis.payload, run.metadata, lang=lang))
    out_pdf = args.output or Path(f"{safe_filename(args.run_id)}_report.pdf")
    try:
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(pdf)
    except OSError as exc:
        print(f"Error: failed to write PDF: {exc}", file=sys.stderr)
        return 1
    print(f"wrote report: {out_pdf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
