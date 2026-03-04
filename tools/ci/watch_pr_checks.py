#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

SUCCESS_CONCLUSION = "SUCCESS"
MERGE_ISSUE_STATES = {"DIRTY", "BEHIND", "BLOCKED", "UNKNOWN"}


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _fetch_pr_status(
    pr: str, repo: str | None
) -> tuple[list[dict[str, object]], str, str]:
    cmd = [
        "gh",
        "pr",
        "view",
        pr,
        "--json",
        "statusCheckRollup,mergeStateStatus,mergeable",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    raw = subprocess.check_output(cmd, text=True)
    payload = json.loads(raw)
    checks = payload.get("statusCheckRollup")
    merge_state = str(payload.get("mergeStateStatus") or "")
    mergeable = str(payload.get("mergeable") or "")
    return (checks if isinstance(checks, list) else [], merge_state, mergeable)


def _has_merge_issues(merge_state: str, mergeable: str) -> bool:
    merge_state_clean = merge_state.strip().upper()
    mergeable_clean = mergeable.strip().upper()
    return merge_state_clean in MERGE_ISSUE_STATES or mergeable_clean == "CONFLICTING"


def _label(check: dict[str, object]) -> str:
    workflow = str(check.get("workflowName") or "").strip()
    name = str(check.get("name") or "").strip()
    if workflow and workflow != name:
        return f"{workflow}/{name}"
    return name or "(unnamed-check)"


def _is_green(check: dict[str, object]) -> bool:
    return (
        str(check.get("status") or "") == "COMPLETED"
        and str(check.get("conclusion") or "") == SUCCESS_CONCLUSION
    )


def _is_non_green_terminal(check: dict[str, object]) -> bool:
    status = str(check.get("status") or "")
    conclusion = str(check.get("conclusion") or "")
    return status == "COMPLETED" and conclusion != SUCCESS_CONCLUSION


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Watch GitHub PR checks every N seconds and exit on non-green or all-green."
    )
    parser.add_argument("--pr", required=True, help="PR number or URL")
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Poll interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--repo", default=None, help="Optional repo in OWNER/REPO format"
    )
    args = parser.parse_args()

    if args.interval <= 0:
        print("interval must be > 0", file=sys.stderr)
        return 2

    while True:
        checks, merge_state, mergeable = _fetch_pr_status(args.pr, args.repo)
        print(
            f"[{_now_utc()}] PR {args.pr}: {len(checks)} checks "
            f"(merge_state={merge_state or 'UNKNOWN'}, mergeable={mergeable or 'UNKNOWN'})"
        )

        if _has_merge_issues(merge_state, mergeable):
            print(
                "RESULT=MERGE_ISSUES "
                f"(merge_state={merge_state or 'UNKNOWN'}, mergeable={mergeable or 'UNKNOWN'})"
            )
            return 3

        if not checks:
            print("No checks found yet; waiting...")
            time.sleep(args.interval)
            continue

        for check in checks:
            label = _label(check)
            status = str(check.get("status") or "")
            conclusion = str(check.get("conclusion") or "")
            print(f"- {label}: status={status}, conclusion={conclusion}")

        if any(_is_non_green_terminal(check) for check in checks):
            print("RESULT=NON_GREEN")
            return 2

        if all(_is_green(check) for check in checks):
            print("RESULT=ALL_GREEN")
            return 0

        print(f"RESULT=PENDING (next poll in {args.interval}s)")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
