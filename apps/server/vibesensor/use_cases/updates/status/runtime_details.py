"""Runtime/build metadata collection for update status reporting."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

import msgspec

from vibesensor.use_cases.updates.models import UpdateRuntimeDetails

LOGGER = logging.getLogger(__name__)

UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"
_PACKAGED_STATIC_DIR = Path(__file__).resolve().parents[3] / "static"


class _UiBuildMetadataRecord(msgspec.Struct, kw_only=True, frozen=True):
    """Typed runtime-details sidecar record stored beside built static assets."""

    ui_source_hash: object = ""
    static_assets_hash: object = ""
    git_commit: object = ""


def _ui_build_metadata_from_json(raw: bytes | str) -> _UiBuildMetadataRecord:
    """Decode one UI build sidecar payload with current fallback semantics."""

    try:
        return msgspec.json.decode(raw, type=_UiBuildMetadataRecord)
    except (msgspec.DecodeError, msgspec.ValidationError, TypeError):
        return _UiBuildMetadataRecord()


def _ui_build_metadata_text(value: object) -> str:
    return str(value or "")


def hash_tree(root: Path, *, ignore_names: set[str]) -> str:
    """Deterministic SHA-256 of a directory tree (sorted, filtered)."""
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


def collect_runtime_details(repo: Path) -> UpdateRuntimeDetails:
    """Collect runtime versioning and static-asset verification details."""
    ui_root = repo / "apps" / "ui"
    static_root = repo / "apps" / "server" / "vibesensor" / "static"
    metadata_path = static_root / UI_BUILD_METADATA_FILE

    try:
        from vibesensor import __version__

        version = __version__
    except ImportError:
        LOGGER.debug("vibesensor.__version__ not available", exc_info=True)
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
    ui_source_hash = hash_tree(
        ui_root,
        ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
    )
    static_assets_hash = hash_tree(static_root, ignore_names={UI_BUILD_METADATA_FILE})

    metadata = _UiBuildMetadataRecord()
    if metadata_path.is_file():
        try:
            metadata = _ui_build_metadata_from_json(metadata_path.read_bytes())
        except OSError:
            metadata = _UiBuildMetadataRecord()

    static_build_source_hash = _ui_build_metadata_text(metadata.ui_source_hash)
    static_build_assets_hash = _ui_build_metadata_text(metadata.static_assets_hash)
    static_build_commit = _ui_build_metadata_text(metadata.git_commit)
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
    return UpdateRuntimeDetails(
        version=version,
        commit=commit,
        ui_source_hash=ui_source_hash,
        static_assets_hash=static_assets_hash,
        static_build_source_hash=static_build_source_hash,
        static_build_commit=static_build_commit,
        assets_verified=assets_verified,
        has_packaged_static=has_packaged_static,
    )
