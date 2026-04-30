#!/usr/bin/env python3
"""Generate local act event payloads from the current checkout."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PullRequestRefs:
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str


def _git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _git_has_ref(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def resolve_base_ref(requested: str | None) -> str:
    candidates = [requested] if requested else ["origin/main", "main"]
    for candidate in candidates:
        if candidate and _git_has_ref(candidate):
            return candidate
    raise SystemExit(
        "No base ref found. Fetch origin/main or rerun with --base-ref <ref> "
        "(for example main)."
    )


def resolve_pull_request_refs(requested_base_ref: str | None) -> PullRequestRefs:
    base_ref = resolve_base_ref(requested_base_ref)
    try:
        base_sha = _git_output("merge-base", base_ref, "HEAD")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Unable to find a common ancestor between {base_ref} and HEAD. "
            "Fetch the latest history or rerun with --base-ref <ref>."
        ) from exc
    return PullRequestRefs(
        base_ref=base_ref,
        base_sha=base_sha,
        head_ref=_git_output("rev-parse", "--abbrev-ref", "HEAD"),
        head_sha=_git_output("rev-parse", "HEAD"),
    )


def build_pull_request_event(refs: PullRequestRefs) -> dict[str, Any]:
    return {
        "pull_request": {
            "base": {
                "ref": refs.base_ref,
                "sha": refs.base_sha,
            },
            "head": {
                "ref": refs.head_ref,
                "sha": refs.head_sha,
            },
        }
    }


def write_pull_request_event(path: Path, refs: PullRequestRefs) -> None:
    path.write_text(
        json.dumps(build_pull_request_event(refs), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Base ref for the generated pull_request event (default: origin/main, then main).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the generated event JSON.",
    )
    args = parser.parse_args(argv)

    refs = resolve_pull_request_refs(args.base_ref)
    write_pull_request_event(args.output, refs)
    print(
        "[act-event] "
        f"base={refs.base_ref}@{refs.base_sha} "
        f"head={refs.head_ref}@{refs.head_sha} "
        f"event={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
