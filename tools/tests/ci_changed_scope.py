#!/usr/bin/env python3
"""Compute changed-path-based CI job gating outputs for GitHub Actions."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from ci_path_rules import workflow_job_selection

ROOT = Path(__file__).resolve().parents[2]
_FORCE_FULL_STACK_ENV = "VIBESENSOR_CI_FORCE_FULL_STACK"


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _changed_files_for_merge_base(base_ref: str, head_ref: str) -> tuple[str, ...]:
    merge_base = _git_output("merge-base", base_ref, head_ref)
    lines = _git_output("diff", "--name-only", f"{merge_base}..{head_ref}").splitlines()
    return tuple(line for line in lines if line.strip())


def _changed_files_for_range(base_sha: str, head_sha: str) -> tuple[str, ...]:
    lines = _git_output("diff", "--name-only", f"{base_sha}..{head_sha}").splitlines()
    return tuple(line for line in lines if line.strip())


def _safe_full_stack_outputs(reason: str) -> dict[str, str]:
    print(f"[ci-scope] {reason}; defaulting to the full stack", file=sys.stderr)
    return workflow_job_selection(()).github_outputs()


def _selection_for_github_event() -> dict[str, str]:
    if os.environ.get(_FORCE_FULL_STACK_ENV, "").strip() == "1":
        print(
            f"[ci-scope] {_FORCE_FULL_STACK_ENV}=1; forcing full-stack scope",
            file=sys.stderr,
        )
        return workflow_job_selection(()).github_outputs()

    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_name or not event_path:
        raise ValueError("GITHUB_EVENT_NAME and GITHUB_EVENT_PATH are required")

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    if event_name == "pull_request":
        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, dict):
            raise ValueError("pull_request payload is missing")
        base = pull_request.get("base")
        head = pull_request.get("head")
        if not isinstance(base, dict) or not isinstance(head, dict):
            raise ValueError("pull_request base/head payload is incomplete")
        base_sha = str(base.get("sha", "")).strip()
        head_sha = str(head.get("sha", "")).strip()
        changed_files = _changed_files_for_merge_base(base_sha, head_sha)
    elif event_name == "push":
        before = str(payload.get("before", "")).strip()
        after = str(payload.get("after", "")).strip()
        if before and after and set(before) != {"0"}:
            changed_files = _changed_files_for_range(before, after)
        else:
            changed_files = _changed_files_for_merge_base("HEAD^", "HEAD")
    else:
        changed_files = _changed_files_for_merge_base("origin/main", "HEAD")
    return workflow_job_selection(changed_files).github_outputs()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--github-output",
        help="Write GitHub Actions outputs to this file instead of stdout.",
    )
    args = parser.parse_args()

    try:
        outputs = _selection_for_github_event()
    except (
        FileNotFoundError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        outputs = _safe_full_stack_outputs(
            f"unable to determine changed-file scope ({exc})"
        )

    output_lines = [f"{key}={value}" for key, value in outputs.items()]
    if args.github_output:
        Path(args.github_output).write_text(
            "".join(f"{line}\n" for line in output_lines),
            encoding="utf-8",
        )
    else:
        for line in output_lines:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
