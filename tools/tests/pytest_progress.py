#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

_PROGRESS_CHARS = {
    ".": "passed",
    "F": "failed",
    "E": "errors",
    "s": "skipped",
    "x": "xfailed",
    "X": "xpassed",
}


@dataclass(slots=True)
class ProgressStats:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0

    @property
    def done(self) -> int:
        return (
            self.passed
            + self.failed
            + self.errors
            + self.skipped
            + self.xfailed
            + self.xpassed
        )


def _parse_collected_total(output: str) -> int | None:
    match = re.search(r"(\d+)\s+tests?\s+collected", output)
    if match:
        return int(match.group(1))
    match = re.search(r"collected\s+(\d+)\s+items", output)
    if match:
        return int(match.group(1))
    return None


def _parse_collected_test_ids(output: str) -> list[str]:
    test_ids: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "::" not in line:
            continue
        if line.startswith("=") or line.startswith("<"):
            continue
        if line.endswith("]") and "[" in line and "%" in line:
            continue
        if line.startswith("tests/") or line.startswith("apps/server/tests/"):
            test_ids.append(line)
    return test_ids


def _parse_deselected_count(line: str) -> int | None:
    match = re.search(r"(\d+)\s+deselected", line)
    if match:
        return int(match.group(1))
    return None


def _format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    mins, sec = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs:d}:{mins:02d}:{sec:02d}"
    return f"{mins:02d}:{sec:02d}"


def _collect_total(
    pytest_args: list[str], timeout_s: int
) -> tuple[int | None, list[str]]:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return None, []
    if result.returncode != 0:
        return None, []
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    return _parse_collected_total(combined), _parse_collected_test_ids(
        result.stdout or ""
    )


def _consume_progress(stats: ProgressStats, text: str) -> None:
    match = re.match(r"^\s*([.FsxXE]+)\s*(?:\[[^\]]+\])?\s*$", text.rstrip("\n"))
    if not match:
        return
    for char in match.group(1):
        field = _PROGRESS_CHARS.get(char)
        if field is not None:
            setattr(stats, field, getattr(stats, field) + 1)


def _consume_verbose_result(stats: ProgressStats, text: str) -> None:
    match = re.search(r"\s(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", text)
    if not match:
        return
    outcome = match.group(1)
    field_map = {
        "PASSED": "passed",
        "FAILED": "failed",
        "ERROR": "errors",
        "SKIPPED": "skipped",
        "XFAIL": "xfailed",
        "XPASS": "xpassed",
    }
    field = field_map.get(outcome)
    if field is not None:
        setattr(stats, field, getattr(stats, field) + 1)


def _print_status(
    stats: ProgressStats,
    total: int | None,
    started_at: float,
    last_progress_at: float,
    next_test: str | None,
) -> None:
    elapsed = max(0.001, time.time() - started_at)
    rate = stats.done / elapsed
    if total and total > 0:
        pct = (stats.done / total) * 100
        remaining = max(0, total - stats.done)
        eta = remaining / rate if rate > 0 else 0
        progress = f"{stats.done}/{total} ({pct:5.1f}%)"
        eta_text = _format_seconds(eta)
    else:
        progress = f"{stats.done} done"
        eta_text = "n/a"
    idle_text = _format_seconds(time.time() - last_progress_at)
    next_label = next_test or "unknown"
    print(
        "[pytest-progress]"
        f" progress={progress}"
        f" pass={stats.passed}"
        f" fail={stats.failed}"
        f" err={stats.errors}"
        f" skip={stats.skipped}"
        f" xfail={stats.xfailed}"
        f" xpass={stats.xpassed}"
        f" rate={rate:.2f}/s"
        f" elapsed={_format_seconds(elapsed)}"
        f" eta={eta_text}"
        f" idle_for={idle_text}"
        f" next={next_label}",
        flush=True,
    )


def run_with_progress(
    pytest_args: list[str],
    update_seconds: float,
    collect_timeout: int,
    show_test_names: bool,
) -> int:
    total, collected_test_ids = _collect_total(pytest_args, timeout_s=collect_timeout)
    print(
        "[pytest-progress]"
        f" collected_total={total if total is not None else 'unknown'}"
        f" args={' '.join(pytest_args) if pytest_args else '(none)'}",
        flush=True,
    )

    if show_test_names:
        cmd = [sys.executable, "-m", "pytest", "-vv", *pytest_args]
    else:
        cmd = [sys.executable, "-m", "pytest", "-q", *pytest_args]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    stats = ProgressStats()
    started_at = time.time()
    last_progress_at = started_at
    effective_total = total
    stats_lock = threading.Lock()
    stop_event = threading.Event()

    def _heartbeat() -> None:
        while not stop_event.wait(update_seconds):
            with stats_lock:
                snapshot = ProgressStats(
                    passed=stats.passed,
                    failed=stats.failed,
                    errors=stats.errors,
                    skipped=stats.skipped,
                    xfailed=stats.xfailed,
                    xpassed=stats.xpassed,
                )
                current_last_progress_at = last_progress_at
                current_effective_total = effective_total

            next_test = None
            if collected_test_ids:
                next_index = min(snapshot.done, len(collected_test_ids) - 1)
                next_test = collected_test_ids[next_index]

            _print_status(
                snapshot,
                current_effective_total,
                started_at,
                current_last_progress_at,
                next_test,
            )

    heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat_thread.start()

    assert process.stdout is not None
    for line in process.stdout:
        with stats_lock:
            before_done = stats.done
            _consume_progress(stats, line)
            _consume_verbose_result(stats, line)
            if stats.done != before_done:
                last_progress_at = time.time()
            deselected = _parse_deselected_count(line)
            if deselected is not None and total is not None:
                effective_total = max(0, total - deselected)
        sys.stdout.write(line)
        sys.stdout.flush()

    return_code = process.wait()
    stop_event.set()
    heartbeat_thread.join(timeout=1.0)
    with stats_lock:
        snapshot = ProgressStats(
            passed=stats.passed,
            failed=stats.failed,
            errors=stats.errors,
            skipped=stats.skipped,
            xfailed=stats.xfailed,
            xpassed=stats.xpassed,
        )
        current_last_progress_at = last_progress_at
        current_effective_total = effective_total
    next_test = None
    if collected_test_ids and snapshot.done < len(collected_test_ids):
        next_test = collected_test_ids[snapshot.done]
    _print_status(
        snapshot,
        current_effective_total,
        started_at,
        current_last_progress_at,
        next_test,
    )
    print(f"[pytest-progress] exit_code={return_code}", flush=True)
    return return_code


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pytest with live progress summary (counts, rate, ETA)."
    )
    parser.add_argument(
        "--update-seconds",
        type=float,
        default=10.0,
        help="How often to print progress summaries while tests are running.",
    )
    parser.add_argument(
        "--collect-timeout",
        type=int,
        default=120,
        help="Timeout in seconds for the pre-run --collect-only step.",
    )
    parser.add_argument(
        "--show-test-names",
        action="store_true",
        help="Run pytest in verbose mode and track progress by individual test results.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to pytest. Prefix with '--' to separate.",
    )
    args = parser.parse_args()
    if args.pytest_args and args.pytest_args[0] == "--":
        args.pytest_args = args.pytest_args[1:]
    return args


def main() -> int:
    args = _parse_args()
    try:
        return run_with_progress(
            pytest_args=list(args.pytest_args),
            update_seconds=max(1.0, float(args.update_seconds)),
            collect_timeout=max(5, int(args.collect_timeout)),
            show_test_names=bool(args.show_test_names),
        )
    except KeyboardInterrupt:
        print("[pytest-progress] interrupted", flush=True)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
