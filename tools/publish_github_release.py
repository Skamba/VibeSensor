#!/usr/bin/env python3
"""Create or update a GitHub release and upload assets via the GitHub CLI."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _run(
    command: list[str], *, check: bool = True, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _repo_api_endpoint(repo: str, path: str) -> str:
    return f"repos/{repo}/{path.lstrip('/')}"


def _existing_release_id(repo: str, tag: str) -> int | None:
    result = _run(
        [
            "gh",
            "api",
            _repo_api_endpoint(repo, f"releases/tags/{tag}"),
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    payload = json.loads(result.stdout)
    release_id = payload.get("id")
    if not isinstance(release_id, int):
        raise SystemExit(
            f"Unexpected release payload for tag {tag!r}: missing integer id"
        )
    return release_id


def _validate_assets(asset_paths: list[str]) -> list[str]:
    missing = [path for path in asset_paths if not Path(path).is_file()]
    if missing:
        raise SystemExit(f"missing release assets: {', '.join(missing)}")
    return asset_paths


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Create or update a GitHub release and upload assets."
    )
    parser.add_argument("--repo", required=True, help="Repository in OWNER/REPO form.")
    parser.add_argument("--tag", required=True, help="Release tag name.")
    parser.add_argument("--target", required=True, help="Target branch or commit SHA.")
    parser.add_argument("--title", required=True, help="Release title.")
    parser.add_argument(
        "--notes-file", required=True, help="Path to the release notes file."
    )
    parser.add_argument(
        "--make-latest",
        choices=("omit", "true", "false", "legacy"),
        default="omit",
        help="Value for the REST release make_latest field.",
    )
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        help="Asset file to upload. Repeat for multiple files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the computed release payload and assets without calling GitHub.",
    )
    args = parser.parse_args(argv)

    notes_path = Path(args.notes_file)
    if not notes_path.is_file():
        raise SystemExit(f"notes file does not exist: {notes_path}")

    assets = _validate_assets(list(args.asset))
    payload: dict[str, object] = {
        "tag_name": args.tag,
        "target_commitish": args.target,
        "name": args.title,
        "body": notes_path.read_text(encoding="utf-8"),
        "draft": False,
        "prerelease": False,
    }
    if args.make_latest != "omit":
        payload["make_latest"] = args.make_latest

    if args.dry_run:
        print(json.dumps({"payload": payload, "assets": assets}, indent=2))
        return

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        json.dump(payload, handle)
        handle.flush()
        payload_file = handle.name

    try:
        release_id = _existing_release_id(args.repo, args.tag)
        if release_id is None:
            _run(
                [
                    "gh",
                    "api",
                    "--method",
                    "POST",
                    "-H",
                    "Accept: application/vnd.github+json",
                    _repo_api_endpoint(args.repo, "releases"),
                    "--input",
                    payload_file,
                ]
            )
        else:
            _run(
                [
                    "gh",
                    "api",
                    "--method",
                    "PATCH",
                    "-H",
                    "Accept: application/vnd.github+json",
                    _repo_api_endpoint(args.repo, f"releases/{release_id}"),
                    "--input",
                    payload_file,
                ]
            )
        _run(
            [
                "gh",
                "release",
                "upload",
                args.tag,
                *assets,
                "--clobber",
                "-R",
                args.repo,
            ]
        )
    finally:
        Path(payload_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1:])
