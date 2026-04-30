#!/usr/bin/env python3
"""Watch GitHub PR checks with compact state-change output."""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
COMPLETED_STATUS = "COMPLETED"
RUNNING_STATUSES = {"IN_PROGRESS"}
QUEUED_STATUSES = {"EXPECTED", "PENDING", "QUEUED", "REQUESTED", "WAITING"}
SUCCESS_CONCLUSIONS = {"NEUTRAL", "SKIPPED", "SUCCESS"}
ACTIONABLE_MERGE_STATES = {"DIRTY"}
DEFAULT_GH_TIMEOUT_S = 30
DEFAULT_FETCH_FAILURE_LIMIT = 3
_REPO_TOOLING_SUPPORT_PATH = ROOT / "tools" / "repo_tooling_support.py"


def _load_repo_tooling_support_module():
    spec = importlib.util.spec_from_file_location(
        "repo_tooling_support_for_watch_pr_checks",
        _REPO_TOOLING_SUPPORT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {_REPO_TOOLING_SUPPORT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_REPO_TOOLING_SUPPORT = _load_repo_tooling_support_module()
_REPO_TOOLING_SUPPORT.ensure_repo_python_version(
    ROOT, script_path=Path(__file__).resolve()
)


@dataclass(frozen=True)
class CheckSnapshot:
    label: str
    bucket: str
    status: str
    conclusion: str
    details_url: str


@dataclass(frozen=True)
class PrStatusSnapshot:
    checks: dict[str, CheckSnapshot]
    merge_state: str
    mergeable: str
    head_sha: str


class MergeFailed(RuntimeError):
    """Raised when merge-on-green cannot complete the PR merge."""


class GhCommandFailed(RuntimeError):
    """Raised when a bounded GitHub CLI call fails before producing usable data."""


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _now_monotonic() -> float:
    return time.monotonic()


def _sleep(seconds: int) -> None:
    time.sleep(seconds)


def _upper(value: object) -> str:
    return str(value or "").strip().upper()


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _compact_error_message(
    text: str,
    *,
    limit: int = 200,
    empty_message: str = "gh command failed without an error message",
) -> str:
    collapsed = " ".join(text.split())
    if not collapsed:
        return empty_message
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3]}..."


def _gh_failure_category(text: str, *, timed_out: bool = False) -> str:
    if timed_out:
        return "timeout"
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "authentication",
            "auth",
            "login",
            "oauth",
            "permission",
            "forbidden",
            "401",
            "403",
        )
    ):
        return "auth"
    if any(
        token in lowered
        for token in (
            "api",
            "graphql",
            "rate limit",
            "http 5",
            "500",
            "502",
            "503",
            "504",
        )
    ):
        return "api"
    if any(
        token in lowered
        for token in (
            "network",
            "connection",
            "could not resolve",
            "timed out",
            "timeout",
            "tls",
            "temporary failure",
        )
    ):
        return "network"
    return "gh"


def _format_gh_failure(
    action: str,
    *,
    category: str,
    detail: str,
) -> str:
    return f"{category}: {action} {detail}"


def _run_gh(
    cmd: Sequence[str],
    *,
    action: str,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(
            part
            for part in (
                _coerce_output(exc.stderr),
                _coerce_output(exc.stdout),
            )
            if part
        )
        detail = f"timed out after {timeout_s}s"
        if output:
            detail = f"{detail}: {_compact_error_message(output)}"
        raise GhCommandFailed(
            _format_gh_failure(
                action,
                category="timeout",
                detail=detail,
            )
        ) from exc


def _fetch_pr_status(
    pr: str,
    repo: str | None,
    *,
    timeout_s: int = DEFAULT_GH_TIMEOUT_S,
) -> PrStatusSnapshot:
    cmd = [
        "gh",
        "pr",
        "view",
        pr,
        "--json",
        "statusCheckRollup,mergeStateStatus,mergeable,headRefOid",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    proc = _run_gh(cmd, action="gh pr view", timeout_s=timeout_s)
    if proc.returncode != 0:
        output = "\n".join(part for part in (proc.stderr, proc.stdout) if part)
        category = _gh_failure_category(output)
        detail = (
            f"exited {proc.returncode}: "
            f"{_compact_error_message(output, empty_message='no stderr/stdout')}"
        )
        raise GhCommandFailed(
            _format_gh_failure("gh pr view", category=category, detail=detail)
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise GhCommandFailed(
            _format_gh_failure(
                "gh pr view",
                category="api",
                detail=f"returned malformed JSON: {exc.msg}",
            )
        ) from exc
    checks_raw = payload.get("statusCheckRollup")
    return PrStatusSnapshot(
        checks=_snapshot_checks(checks_raw) if isinstance(checks_raw, list) else {},
        merge_state=str(payload.get("mergeStateStatus") or ""),
        mergeable=str(payload.get("mergeable") or ""),
        head_sha=str(payload.get("headRefOid") or "").strip(),
    )


def _actionable_merge_issue(merge_state: str, mergeable: str) -> str | None:
    merge_state_clean = _upper(merge_state)
    mergeable_clean = _upper(mergeable)
    if merge_state_clean in ACTIONABLE_MERGE_STATES:
        return f"merge_state={merge_state_clean}"
    if mergeable_clean == "CONFLICTING":
        return f"mergeable={mergeable_clean}"
    return None


def _label(check: dict[str, object]) -> str:
    workflow = str(check.get("workflowName") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if workflow and workflow != name:
        return f"{workflow}/{name}"
    return name or "(unnamed-check)"


def _bucket_for_check(check: dict[str, object]) -> tuple[str, str, str]:
    status = _upper(check.get("status"))
    conclusion = _upper(check.get("conclusion"))
    state = _upper(check.get("state"))

    if status == COMPLETED_STATUS:
        if conclusion in SUCCESS_CONCLUSIONS:
            return ("ok", status, conclusion)
        return ("failed", status, conclusion or "FAILED")

    if status in RUNNING_STATUSES:
        return ("running", status, conclusion or status)

    if status:
        return ("queued", status, conclusion or status)

    if state in SUCCESS_CONCLUSIONS:
        return ("ok", COMPLETED_STATUS, state)
    if state in QUEUED_STATUSES or not state:
        return ("queued", state or "PENDING", state or "PENDING")
    return ("failed", COMPLETED_STATUS, state)


def _snapshot_check(check: dict[str, object]) -> CheckSnapshot:
    bucket, status, conclusion = _bucket_for_check(check)
    return CheckSnapshot(
        label=_label(check),
        bucket=bucket,
        status=status,
        conclusion=conclusion,
        details_url=str(
            check.get("detailsUrl") or check.get("targetUrl") or ""
        ).strip(),
    )


def _snapshot_checks(checks: list[dict[str, object]]) -> dict[str, CheckSnapshot]:
    return {
        snapshot.label: snapshot
        for snapshot in sorted(map(_snapshot_check, checks), key=_sort_key)
    }


def _sort_key(snapshot: CheckSnapshot) -> tuple[str, str]:
    return (snapshot.label, snapshot.details_url)


def _summary_counts(checks: dict[str, CheckSnapshot]) -> dict[str, int]:
    counts = {"ok": 0, "running": 0, "queued": 0, "failed": 0, "total": len(checks)}
    for snapshot in checks.values():
        counts[snapshot.bucket] += 1
    return counts


def _summary_line(pr: str, checks: dict[str, CheckSnapshot]) -> str:
    counts = _summary_counts(checks)
    if counts["total"] == 0:
        return f"[{_now_utc()}] PR {pr} waiting for checks"
    if counts["failed"]:
        return (
            f"[{_now_utc()}] PR {pr} failing ok={counts['ok']} running={counts['running']} "
            f"queued={counts['queued']} failed={counts['failed']} total={counts['total']}"
        )
    if counts["running"] or counts["queued"]:
        return (
            f"[{_now_utc()}] PR {pr} pending ok={counts['ok']} running={counts['running']} "
            f"queued={counts['queued']} total={counts['total']}"
        )
    return f"[{_now_utc()}] PR {pr} green ok={counts['ok']} total={counts['total']}"


def _transition_line(
    previous: CheckSnapshot | None, current: CheckSnapshot
) -> str | None:
    if previous == current:
        return None

    if previous is None:
        if current.bucket == "ok":
            return None
        if current.bucket == "running":
            return f"START {current.label}"
        if current.bucket == "queued":
            return f"QUEUE {current.label}"
        return _failure_line(current)

    if previous.bucket == current.bucket and previous.conclusion == current.conclusion:
        return None

    if current.bucket == "running":
        return f"START {current.label}"
    if current.bucket == "queued":
        return f"QUEUE {current.label}"
    if current.bucket == "ok":
        return f"DONE {current.label} ({current.conclusion.lower()})"
    return _failure_line(current)


def _failure_line(snapshot: CheckSnapshot) -> str:
    suffix = f" {snapshot.details_url}" if snapshot.details_url else ""
    return f"FAIL {snapshot.label} ({snapshot.conclusion.lower()}){suffix}"


def _change_lines(
    previous_checks: dict[str, CheckSnapshot] | None,
    current_checks: dict[str, CheckSnapshot],
    previous_merge_issue: str | None,
    current_merge_issue: str | None,
) -> list[str]:
    lines: list[str] = []
    previous_checks = previous_checks or {}

    for label in sorted(current_checks):
        line = _transition_line(previous_checks.get(label), current_checks[label])
        if line:
            lines.append(line)

    for label in sorted(set(previous_checks) - set(current_checks)):
        snapshot = previous_checks[label]
        if snapshot.bucket in {"queued", "running"}:
            lines.append(f"DROP {snapshot.label}")

    if current_merge_issue and current_merge_issue != previous_merge_issue:
        lines.append(f"MERGE {current_merge_issue}")

    return lines


def _has_failures(checks: dict[str, CheckSnapshot]) -> bool:
    return any(snapshot.bucket == "failed" for snapshot in checks.values())


def _all_green(checks: dict[str, CheckSnapshot]) -> bool:
    return bool(checks) and all(snapshot.bucket == "ok" for snapshot in checks.values())


def _short_sha(head_sha: str) -> str:
    return head_sha[:12] if head_sha else "unknown"


def _merge_pr(
    pr: str,
    repo: str | None,
    head_sha: str,
    *,
    timeout_s: int = DEFAULT_GH_TIMEOUT_S,
) -> None:
    cmd = ["gh", "pr", "merge", pr]
    if repo:
        cmd.extend(["--repo", repo])
    cmd.extend(["--merge", "--delete-branch"])
    if head_sha:
        cmd.extend(["--match-head-commit", head_sha])

    try:
        proc = _run_gh(cmd, action="gh pr merge", timeout_s=timeout_s)
    except GhCommandFailed as exc:
        raise MergeFailed(str(exc)) from exc

    if proc.returncode == 0:
        return

    output = "\n".join(part for part in (proc.stderr, proc.stdout) if part)
    raise MergeFailed(
        _format_gh_failure(
            "gh pr merge",
            category=_gh_failure_category(output),
            detail=(
                f"exited {proc.returncode}: "
                f"{_compact_error_message(output, empty_message='no stderr/stdout')}"
            ),
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Watch GitHub PR checks with compact state-change output."
    )
    parser.add_argument("--pr", required=True, help="PR number or URL")
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Poll interval in seconds (default: 10)",
    )
    parser.add_argument(
        "--heartbeat",
        type=int,
        default=120,
        help="Print a reminder summary after N quiet seconds; 0 disables it (default: 120)",
    )
    parser.add_argument(
        "--repo", default=None, help="Optional repo in OWNER/REPO format"
    )
    parser.add_argument(
        "--merge-on-green",
        action="store_true",
        help="Merge the PR via gh as soon as checks are green",
    )
    parser.add_argument(
        "--gh-timeout",
        type=int,
        default=DEFAULT_GH_TIMEOUT_S,
        help=f"Timeout for each gh CLI call in seconds (default: {DEFAULT_GH_TIMEOUT_S})",
    )
    parser.add_argument(
        "--fetch-failure-limit",
        type=int,
        default=DEFAULT_FETCH_FAILURE_LIMIT,
        help=(
            "Consecutive gh pr view failures to tolerate before RESULT=FETCH_FAILED "
            f"(default: {DEFAULT_FETCH_FAILURE_LIMIT})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.interval <= 0:
        print("interval must be > 0", file=sys.stderr)
        return 2
    if args.heartbeat < 0:
        print("heartbeat must be >= 0", file=sys.stderr)
        return 2
    if args.gh_timeout <= 0:
        print("gh-timeout must be > 0", file=sys.stderr)
        return 2
    if args.fetch_failure_limit <= 0:
        print("fetch-failure-limit must be > 0", file=sys.stderr)
        return 2

    previous_checks: dict[str, CheckSnapshot] | None = None
    previous_merge_issue: str | None = None
    last_summary_at = 0.0
    consecutive_fetch_failures = 0

    while True:
        try:
            snapshot = _fetch_pr_status(
                args.pr,
                args.repo,
                timeout_s=args.gh_timeout,
            )
        except GhCommandFailed as exc:
            consecutive_fetch_failures += 1
            print(
                f"[{_now_utc()}] WARN gh pr view failed "
                f"attempt {consecutive_fetch_failures}/{args.fetch_failure_limit}: {exc}"
            )
            if consecutive_fetch_failures >= args.fetch_failure_limit:
                print(f"RESULT=FETCH_FAILED ({exc})")
                return 5
            _sleep(args.interval)
            continue

        consecutive_fetch_failures = 0
        current_checks = snapshot.checks
        current_merge_issue = _actionable_merge_issue(
            snapshot.merge_state, snapshot.mergeable
        )
        changes = _change_lines(
            previous_checks,
            current_checks,
            previous_merge_issue=previous_merge_issue,
            current_merge_issue=current_merge_issue,
        )

        now = _now_monotonic()
        summary_needed = previous_checks is None or bool(changes)
        if (
            not summary_needed
            and args.heartbeat
            and now - last_summary_at >= args.heartbeat
        ):
            summary_needed = True

        if summary_needed:
            print(_summary_line(args.pr, current_checks))
            last_summary_at = now
        for line in changes:
            print(line)

        if _has_failures(current_checks):
            print("RESULT=NON_GREEN")
            return 2

        if current_merge_issue:
            print(f"RESULT=MERGE_ISSUES ({current_merge_issue})")
            return 3

        if _all_green(current_checks):
            if args.merge_on_green:
                try:
                    _merge_pr(
                        args.pr,
                        args.repo,
                        snapshot.head_sha,
                        timeout_s=args.gh_timeout,
                    )
                except MergeFailed as exc:
                    print(f"RESULT=MERGE_FAILED ({exc})")
                    return 4
                print(f"MERGED PR {args.pr} head={_short_sha(snapshot.head_sha)}")
                print("RESULT=MERGED")
                return 0
            print("RESULT=ALL_GREEN")
            return 0

        previous_checks = current_checks
        previous_merge_issue = current_merge_issue
        _sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
