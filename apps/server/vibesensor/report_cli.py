from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import map_summary, summarize_log
from .report.pdf_builder import build_report_pdf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate VibeSensor PDF report from a run log")
    parser.add_argument("input", type=Path, help="Input run file (.jsonl)")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output PDF path (default: <input_stem>_report.pdf)",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=None,
        help="Optional path to write computed summary JSON",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"Error: input file not found: {args.input}", file=__import__("sys").stderr)
        return 1
    try:
        include_samples = args.summary_json is not None
        summary = summarize_log(args.input, include_samples=include_samples)
    except json.JSONDecodeError as exc:
        print(f"Error: input file contains invalid JSON: {exc}", file=__import__("sys").stderr)
        return 1
    except ValueError as exc:
        print(f"Error: {exc}", file=__import__("sys").stderr)
        return 1

    out_pdf = args.output or args.input.with_name(f"{args.input.stem}_report.pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    try:
        out_pdf.write_bytes(build_report_pdf(map_summary(summary)))
    except Exception as exc:
        print(
            f"Error: PDF generation failed: {exc}",
            file=__import__("sys").stderr,
        )
        return 1
    print(f"wrote report: {out_pdf}")

    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"wrote summary: {args.summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
