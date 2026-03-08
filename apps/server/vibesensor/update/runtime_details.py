"""Runtime and filesystem detail collection for updater status reporting."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

from ..json_types import JsonObject, is_json_object

LOGGER = logging.getLogger(__name__)

UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"
_PACKAGED_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _hash_tree(root: Path, *, ignore_names: set[str]) -> str:
    if not root.exists():
        return ""
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if any(part in ignore_names for part in relative.parts):
            continue
        hasher.update(str(relative.as_posix()).encode("utf-8"))
        hasher.update(b"\0")
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
        except OSError:
            continue
        hasher.update(b"\0")
    return hasher.hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class UpdateRuntimeDetailsCollector:
    """Collects runtime versioning and static-asset verification details."""

    __slots__ = ("_repo",)

    def __init__(self, *, repo: Path) -> None:
        self._repo = repo

    def collect(self) -> JsonObject:
        repo = self._repo
        ui_root = repo / "apps" / "ui"
        static_root = repo / "apps" / "server" / "vibesensor" / "static"
        metadata_path = static_root / UI_BUILD_METADATA_FILE

        try:
            from vibesensor import __version__

            version = __version__
        except Exception:
            version = "unknown"

        commit = ""
        if (repo / ".git").exists():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "HEAD"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0:
                    commit = proc.stdout.strip()
            except OSError:
                LOGGER.debug("git rev-parse failed; commit hash unavailable", exc_info=True)

        has_packaged_static = (_PACKAGED_STATIC_DIR / "index.html").exists()
        ui_source_hash = _hash_tree(
            ui_root,
            ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
        )
        static_assets_hash = _hash_tree(static_root, ignore_names={UI_BUILD_METADATA_FILE})

        metadata: JsonObject = {}
        if metadata_path.is_file():
            try:
                loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                metadata = loaded if is_json_object(loaded) else {}
            except (OSError, json.JSONDecodeError):
                metadata = {}

        static_build_source_hash = str(metadata.get("ui_source_hash") or "")
        static_build_assets_hash = str(metadata.get("static_assets_hash") or "")
        static_build_commit = str(metadata.get("git_commit") or "")
        has_repo_static = static_root.exists()
        assets_verified = (
            bool(ui_source_hash)
            and bool(static_assets_hash)
            and bool(static_build_source_hash)
            and bool(static_build_assets_hash)
            and ui_source_hash == static_build_source_hash
            and static_assets_hash == static_build_assets_hash
        )
        if not has_repo_static:
            assets_verified = has_packaged_static
        return {
            "version": version,
            "commit": commit,
            "ui_source_hash": ui_source_hash,
            "static_assets_hash": static_assets_hash,
            "static_build_source_hash": static_build_source_hash,
            "static_build_commit": static_build_commit,
            "assets_verified": assets_verified,
            "has_packaged_static": has_packaged_static,
        }
