#!/usr/bin/env python3
"""File/function-size maintainability gate.

This script reports the longest tracked source files and Python functions as a
refactoring signal, then fails when a checked item exceeds the configured
threshold without an explicit allowlist entry.

Guidance:
- Keep files short where practical.
- Do not split files mechanically when doing so hurts readability,
  discoverability, or long-term maintainability.
- Existing oversized files/functions can be allowlisted with a short reason and
  a max line count. Growth above that max fails until it is deliberately
  reviewed.

Exit code is non-zero when a file/function exceeds the configured threshold, an
allowlisted item grows beyond its max, or the allowlist becomes stale.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_tooling_support():
    helper_path = REPO_ROOT / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()

TOP_N = 25
DEFAULT_FILE_THRESHOLD_LINES = 1200
DEFAULT_FUNCTION_THRESHOLD_LINES = 200
DEFAULT_ALLOWLIST = Path("tools/dev/maintainability_allowlist.yml")

# Extensions considered hand-written source
SOURCE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".sh", ".c", ".cpp", ".h"}

# Paths always excluded (build outputs, deps, generated)
EXCLUDE_DIRS = {
    "node_modules",
    ".pio",
    "dist",
    "__pycache__",
    ".cache",
    "artifacts",
    ".venv",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
}

# Data files that are intentionally large (JSON extracted from code)
EXCLUDE_FILES: set[str] = set()


@dataclass(frozen=True)
class AllowlistEntry:
    max_lines: int
    reason: str


@dataclass(frozen=True)
class MaintainabilityAllowlist:
    file_threshold_lines: int
    function_threshold_lines: int
    files: dict[str, AllowlistEntry]
    functions: dict[str, AllowlistEntry]


@dataclass(frozen=True)
class FileMeasurement:
    path: str
    lines: int


@dataclass(frozen=True)
class FunctionMeasurement:
    path: str
    qualname: str
    start_line: int
    end_line: int
    lines: int

    @property
    def target(self) -> str:
        return f"{self.path}::{self.qualname}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Report the longest source files/functions and fail when they "
            "exceed configured line-count thresholds without an allowlist entry."
        )
    )
    parser.add_argument(
        "--fail-over",
        type=int,
        default=None,
        help=(
            "Deprecated alias for --file-fail-over. Exit non-zero when one or "
            "more checked files exceed this line count."
        ),
    )
    parser.add_argument(
        "--file-fail-over",
        type=int,
        default=None,
        help=(
            f"File line threshold. Defaults to {DEFAULT_FILE_THRESHOLD_LINES}, "
            "or the allowlist threshold when present."
        ),
    )
    parser.add_argument(
        "--function-fail-over",
        type=int,
        default=None,
        help=(
            f"Python function line threshold. Defaults to "
            f"{DEFAULT_FUNCTION_THRESHOLD_LINES}, or the allowlist threshold "
            "when present."
        ),
    )
    parser.add_argument(
        "--allowlist",
        default=str(DEFAULT_ALLOWLIST),
        help=(
            "YAML allowlist with files/functions, max_lines, and reasons. "
            f"Defaults to {DEFAULT_ALLOWLIST}."
        ),
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Only print the report; do not fail on threshold or allowlist drift.",
    )
    args = parser.parse_args(argv)
    for option in ("fail_over", "file_fail_over", "function_fail_over"):
        value = getattr(args, option)
        if value is not None and value < 0:
            parser.error(f"--{option.replace('_', '-')} must be zero or greater")
    if args.fail_over is not None and args.file_fail_over is not None:
        parser.error("--fail-over and --file-fail-over cannot both be set")
    return args


def _read_allowlist_entry(
    section: str, target: str, raw_entry: object
) -> AllowlistEntry:
    if not isinstance(raw_entry, dict):
        raise ValueError(
            f"{section}.{target} must be a mapping with max_lines and reason"
        )
    max_lines = raw_entry.get("max_lines")
    reason = raw_entry.get("reason")
    if not isinstance(max_lines, int) or max_lines < 0:
        raise ValueError(f"{section}.{target}.max_lines must be a non-negative integer")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(f"{section}.{target}.reason must be a non-empty string")
    return AllowlistEntry(max_lines=max_lines, reason=reason.strip())


def _read_allowlist_section(
    section: str, raw_section: object
) -> dict[str, AllowlistEntry]:
    if raw_section is None:
        return {}
    if not isinstance(raw_section, dict):
        raise ValueError(f"{section} must be a mapping")
    entries: dict[str, AllowlistEntry] = {}
    for target, raw_entry in raw_section.items():
        if not isinstance(target, str) or not target:
            raise ValueError(f"{section} keys must be non-empty strings")
        entries[target] = _read_allowlist_entry(section, target, raw_entry)
    return entries


def _read_positive_int(
    raw_data: dict[str, Any],
    key: str,
    default: int,
) -> int:
    raw_value = raw_data.get(key, default)
    if not isinstance(raw_value, int) or raw_value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return raw_value


def _load_allowlist(path: Path) -> MaintainabilityAllowlist:
    if not path.exists():
        return MaintainabilityAllowlist(
            file_threshold_lines=DEFAULT_FILE_THRESHOLD_LINES,
            function_threshold_lines=DEFAULT_FUNCTION_THRESHOLD_LINES,
            files={},
            functions={},
        )
    with path.open(encoding="utf-8") as fh:
        raw_data = yaml.safe_load(fh) or {}
    if not isinstance(raw_data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return MaintainabilityAllowlist(
        file_threshold_lines=_read_positive_int(
            raw_data,
            "file_threshold_lines",
            DEFAULT_FILE_THRESHOLD_LINES,
        ),
        function_threshold_lines=_read_positive_int(
            raw_data,
            "function_threshold_lines",
            DEFAULT_FUNCTION_THRESHOLD_LINES,
        ),
        files=_read_allowlist_section("files", raw_data.get("files")),
        functions=_read_allowlist_section("functions", raw_data.get("functions")),
    )


def _walk_files(repo_root: Path) -> list[str]:
    return _repo_tooling_support.walk_files(repo_root, EXCLUDE_DIRS)


def _tracked_files(repo_root: Path) -> list[str]:
    return _repo_tooling_support.tracked_files(repo_root, EXCLUDE_DIRS)


def _should_check(path: str) -> bool:
    _, ext = os.path.splitext(path)
    if ext not in SOURCE_EXTS:
        return False
    parts = path.split("/")
    for part in parts:
        if part in EXCLUDE_DIRS:
            return False
    if path in EXCLUDE_FILES:
        return False
    return True


class _FunctionLengthVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.stack: list[str] = []
        self.measurements: list[FunctionMeasurement] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        end_line = getattr(node, "end_lineno", None)
        qualname = ".".join((*self.stack, node.name))
        if isinstance(end_line, int):
            self.measurements.append(
                FunctionMeasurement(
                    path=self.path,
                    qualname=qualname,
                    start_line=node.lineno,
                    end_line=end_line,
                    lines=end_line - node.lineno + 1,
                )
            )
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


def _measure_python_functions(repo_root: Path, path: str) -> list[FunctionMeasurement]:
    try:
        source = (repo_root / path).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    visitor = _FunctionLengthVisitor(path)
    visitor.visit(tree)
    return visitor.measurements


def _format_file(path: str, lines: int) -> str:
    return f"{lines:5d}  {path}"


def _format_function(function: FunctionMeasurement) -> str:
    return (
        f"{function.lines:5d}  {function.target}"
        f" ({function.start_line}-{function.end_line})"
    )


def _threshold_failures(
    *,
    files: list[FileMeasurement],
    functions: list[FunctionMeasurement],
    allowlist: MaintainabilityAllowlist,
    file_threshold: int,
    function_threshold: int,
) -> list[str]:
    failures: list[str] = []
    measured_files = {measurement.path: measurement for measurement in files}
    measured_functions = {measurement.target: measurement for measurement in functions}

    for measurement in files:
        if measurement.lines <= file_threshold:
            continue
        entry = allowlist.files.get(measurement.path)
        if entry is None:
            failures.append(
                "file exceeds threshold and is not allowlisted: "
                f"{_format_file(measurement.path, measurement.lines)} "
                f"(threshold {file_threshold})"
            )
            continue
        if measurement.lines > entry.max_lines:
            failures.append(
                "allowlisted file grew past max_lines: "
                f"{_format_file(measurement.path, measurement.lines)} "
                f"(max {entry.max_lines}; reason: {entry.reason})"
            )

    for measurement in functions:
        if measurement.lines <= function_threshold:
            continue
        entry = allowlist.functions.get(measurement.target)
        if entry is None:
            failures.append(
                "function exceeds threshold and is not allowlisted: "
                f"{_format_function(measurement)} (threshold {function_threshold})"
            )
            continue
        if measurement.lines > entry.max_lines:
            failures.append(
                "allowlisted function grew past max_lines: "
                f"{_format_function(measurement)} "
                f"(max {entry.max_lines}; reason: {entry.reason})"
            )

    for target in sorted(allowlist.files):
        measurement = measured_files.get(target)
        if measurement is None:
            failures.append(f"allowlisted file is no longer tracked source: {target}")
        elif measurement.lines <= file_threshold:
            failures.append(
                "allowlisted file no longer exceeds threshold; remove allowlist entry: "
                f"{_format_file(measurement.path, measurement.lines)} "
                f"(threshold {file_threshold})"
            )

    for target in sorted(allowlist.functions):
        measurement = measured_functions.get(target)
        if measurement is None:
            failures.append(f"allowlisted function is no longer measurable: {target}")
        elif measurement.lines <= function_threshold:
            failures.append(
                "allowlisted function no longer exceeds threshold; remove allowlist entry: "
                f"{_format_function(measurement)} (threshold {function_threshold})"
            )

    return failures


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    try:
        allowlist = _load_allowlist(repo_root / args.allowlist)
    except ValueError as error:
        print(f"FAIL: invalid maintainability allowlist: {error}")
        return 1
    file_threshold = args.file_fail_over
    if file_threshold is None:
        file_threshold = (
            args.fail_over
            if args.fail_over is not None
            else allowlist.file_threshold_lines
        )
    function_threshold = (
        args.function_fail_over
        if args.function_fail_over is not None
        else allowlist.function_threshold_lines
    )
    files = [f for f in _tracked_files(repo_root) if _should_check(f)]
    measured_files: list[FileMeasurement] = []
    measured_functions: list[FunctionMeasurement] = []

    for path in files:
        try:
            with open(repo_root / path, encoding="utf-8") as fh:
                loc = sum(1 for _ in fh)
        except (OSError, UnicodeDecodeError):
            continue
        measured_files.append(FileMeasurement(path=path, lines=loc))
        if path.endswith(".py"):
            measured_functions.extend(_measure_python_functions(repo_root, path))

    measured_files.sort(key=lambda item: (-item.lines, item.path))
    measured_functions.sort(key=lambda item: (-item.lines, item.target))

    print(
        "ℹ️  Maintainability size gate: keep files/functions short where practical, "
        "without hurting human maintainability."
    )
    print(
        f"File threshold: {file_threshold} lines; "
        f"Python function threshold: {function_threshold} lines."
    )
    print(f"Showing top {min(TOP_N, len(measured_files))} longest source files:")
    for measurement in measured_files[:TOP_N]:
        print(f"   {_format_file(measurement.path, measurement.lines)}")

    print(
        f"\nShowing top {min(TOP_N, len(measured_functions))} "
        "longest Python functions/methods:"
    )
    for measurement in measured_functions[:TOP_N]:
        print(f"   {_format_function(measurement)}")

    failures = _threshold_failures(
        files=measured_files,
        functions=measured_functions,
        allowlist=allowlist,
        file_threshold=file_threshold,
        function_threshold=function_threshold,
    )
    if failures and not args.advisory:
        print(f"\nFAIL: {len(failures)} maintainability size issue(s):")
        for failure in failures:
            print(f"   - {failure}")
        print(
            "\nSuggestion: refactor/split when it improves clarity, or add a "
            "reviewed allowlist entry with max_lines and a specific reason."
        )
        return 1

    print(
        "\nSuggestion: refactor large files/functions when it improves clarity; "
        "avoid artificial splits that make maintenance harder."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
