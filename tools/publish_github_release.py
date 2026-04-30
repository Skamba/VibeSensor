#!/usr/bin/env python3
"""Create or update a GitHub release and upload assets via the GitHub CLI."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

GH_API_TIMEOUT_SECONDS = 60.0
GH_RELEASE_UPLOAD_TIMEOUT_SECONDS = 30 * 60.0
_OUTPUT_EXCERPT_CHARS = 1200


def _output_excerpt(output: str | None) -> str:
    if not output:
        return ""
    stripped = output.strip()
    if len(stripped) <= _OUTPUT_EXCERPT_CHARS:
        return stripped
    return f"{stripped[:_OUTPUT_EXCERPT_CHARS]}…"


def _run(
    command: list[str],
    *,
    check: bool = True,
    capture_output: bool = False,
    context: str,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=capture_output,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        details = [
            f"{context} timed out after {timeout_s:g}s",
            f"command: {shlex.join(command)}",
        ]
        stdout = _output_excerpt(exc.stdout)
        stderr = _output_excerpt(exc.stderr)
        if stdout:
            details.append(f"stdout: {stdout}")
        if stderr:
            details.append(f"stderr: {stderr}")
        raise SystemExit("\n".join(details)) from exc
    except OSError as exc:
        raise SystemExit(
            f"{context} failed to start: {exc}\ncommand: {shlex.join(command)}"
        ) from exc
    if check and result.returncode != 0:
        details = [
            f"{context} failed with exit code {result.returncode}",
            f"command: {shlex.join(command)}",
        ]
        stdout = _output_excerpt(result.stdout)
        stderr = _output_excerpt(result.stderr)
        if stdout:
            details.append(f"stdout: {stdout}")
        if stderr:
            details.append(f"stderr: {stderr}")
        raise SystemExit("\n".join(details))
    return result


def _repo_api_endpoint(repo: str, path: str) -> str:
    return f"repos/{repo}/{path.lstrip('/')}"


def _existing_release_id(repo: str, tag: str, *, timeout_s: float) -> int | None:
    result = _run(
        [
            "gh",
            "api",
            _repo_api_endpoint(repo, f"releases/tags/{tag}"),
        ],
        check=False,
        capture_output=True,
        context=f"Lookup release {tag!r} in {repo}",
        timeout_s=timeout_s,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        stdout = _output_excerpt(result.stdout)
        raise SystemExit(
            f"Malformed GitHub release lookup JSON for tag {tag!r} in {repo}: "
            f"{exc.msg} at line {exc.lineno} column {exc.colno}"
            + (f"\nstdout: {stdout}" if stdout else "")
        ) from exc
    release_id = payload.get("id")
    if not isinstance(release_id, int):
        raise SystemExit(
            f"Unexpected release payload for tag {tag!r} in {repo}: missing integer id"
        )
    return release_id


def _validate_assets(asset_paths: list[str]) -> list[str]:
    missing = [path for path in asset_paths if not Path(path).is_file()]
    if missing:
        raise SystemExit(f"missing release assets: {', '.join(missing)}")
    return asset_paths


def _positive_timeout(value: str) -> float:
    timeout_s = float(value)
    if timeout_s <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero")
    return timeout_s


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
    parser.add_argument(
        "--gh-api-timeout",
        type=_positive_timeout,
        default=GH_API_TIMEOUT_SECONDS,
        help="Timeout in seconds for GitHub API metadata calls.",
    )
    parser.add_argument(
        "--upload-timeout",
        type=_positive_timeout,
        default=GH_RELEASE_UPLOAD_TIMEOUT_SECONDS,
        help="Timeout in seconds for GitHub release asset uploads.",
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
        release_id = _existing_release_id(
            args.repo, args.tag, timeout_s=args.gh_api_timeout
        )
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
                ],
                capture_output=True,
                context=f"Create release {args.tag!r} in {args.repo}",
                timeout_s=args.gh_api_timeout,
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
                ],
                capture_output=True,
                context=f"Update release {args.tag!r} in {args.repo}",
                timeout_s=args.gh_api_timeout,
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
            ],
            context=f"Upload {len(assets)} asset(s) to release {args.tag!r} in {args.repo}",
            timeout_s=args.upload_timeout,
        )
    finally:
        Path(payload_file).unlink(missing_ok=True)


if __name__ == "__main__":
    main(sys.argv[1:])
