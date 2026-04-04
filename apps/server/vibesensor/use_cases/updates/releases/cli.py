"""Command-line entrypoints for updater release helpers."""

from __future__ import annotations

import argparse
import logging
import sys

from .models import resolve_release_fetcher_config
from .release_fetcher import ServerReleaseFetcher

__all__ = ["fetch_latest_wheel_cli"]


def fetch_latest_wheel_cli() -> None:
    """CLI entry point: fetch the latest server release wheel."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Fetch the latest VibeSensor server wheel from GitHub Releases",
    )
    parser.add_argument("--repo", default="", help="GitHub owner/repo")
    parser.add_argument("--dest", default=".", help="Destination directory for the wheel")
    args = parser.parse_args()

    config = resolve_release_fetcher_config(server_repo=args.repo)
    fetcher = ServerReleaseFetcher(config)

    try:
        release = fetcher.find_latest_release()
        print(f"Latest release: {release.tag} ({release.version})")
        whl = fetcher.download_wheel(release, dest_dir=args.dest)
        print(f"Downloaded: {whl}")
        print(f"SHA256: {release.sha256}")
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).exception("release fetch CLI failed")
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
