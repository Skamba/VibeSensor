#!/usr/bin/env python3
"""Publish files to a GitHub wiki git repository."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

EXCLUDED_GIT_PATHS = {".git"}


def _run(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def _remote_url(
    repo: str | None, token: str | None, explicit_remote: str | None
) -> str:
    if explicit_remote:
        return explicit_remote
    if repo is None:
        raise SystemExit("either --repo or --remote-url is required")
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN is required when publishing to a GitHub wiki remote"
        )
    return f"https://x-access-token:{token}@github.com/{repo}.wiki.git"


def _prepare_checkout(remote_url: str, checkout_dir: Path, branch: str) -> None:
    result = subprocess.run(
        ["git", "clone", remote_url, str(checkout_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return
    checkout_dir.mkdir(parents=True, exist_ok=True)
    _run(["git", "init"], cwd=checkout_dir)
    _run(["git", "checkout", "-b", branch], cwd=checkout_dir)
    _run(["git", "remote", "add", "origin", remote_url], cwd=checkout_dir)


def _remove_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _sync_tree(
    source_dir: Path, checkout_dir: Path, *, preserve_existing: bool = False
) -> None:
    if not preserve_existing:
        for child in checkout_dir.iterdir():
            if child.name in EXCLUDED_GIT_PATHS:
                continue
            _remove_path(child)
    for child in source_dir.iterdir():
        target = checkout_dir / child.name
        _remove_path(target)
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def _has_staged_changes(checkout_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=checkout_dir,
        check=False,
    )
    return result.returncode != 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Publish files into the GitHub wiki remote."
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help=(
            "Directory containing the files to publish into the wiki checkout. "
            "With --preserve-existing, only matching top-level paths are replaced."
        ),
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="GitHub repo in OWNER/REPO form. Used to build the wiki remote URL.",
    )
    parser.add_argument(
        "--remote-url",
        default=None,
        help="Explicit git remote URL for the wiki repository.",
    )
    parser.add_argument(
        "--branch", default="master", help="Wiki branch to push (default: master)."
    )
    parser.add_argument(
        "--commit-message",
        default="docs(wiki): refresh wiki content",
        help="Commit message for the wiki update.",
    )
    parser.add_argument(
        "--author-name", default="github-actions[bot]", help="Git author name."
    )
    parser.add_argument(
        "--author-email",
        default="41898282+github-actions[bot]@users.noreply.github.com",
        help="Git author email.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sync into a temporary checkout and stop before commit/push.",
    )
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help=(
            "Keep wiki files that are not present in --source-dir. "
            "Only matching top-level paths from the source directory are replaced."
        ),
    )
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir).resolve()
    if not source_dir.is_dir():
        raise SystemExit(f"source dir does not exist: {source_dir}")

    token = os.environ.get("GITHUB_TOKEN")
    remote_url = _remote_url(args.repo, token, args.remote_url)

    with tempfile.TemporaryDirectory(prefix="vibesensor-wiki-") as temp_dir:
        checkout_dir = Path(temp_dir) / "wiki"
        _prepare_checkout(remote_url, checkout_dir, args.branch)
        _run(["git", "config", "user.name", args.author_name], cwd=checkout_dir)
        _run(["git", "config", "user.email", args.author_email], cwd=checkout_dir)
        _sync_tree(
            source_dir,
            checkout_dir,
            preserve_existing=args.preserve_existing,
        )
        _run(["git", "add", "-A"], cwd=checkout_dir)

        if not _has_staged_changes(checkout_dir):
            print("No wiki changes to publish")
            return

        if args.dry_run:
            print(f"Dry run: staged wiki update in {checkout_dir}")
            return

        _run(["git", "commit", "-m", args.commit_message], cwd=checkout_dir)
        _run(["git", "push", "origin", args.branch], cwd=checkout_dir)
        print("Published wiki update")


if __name__ == "__main__":
    main()
