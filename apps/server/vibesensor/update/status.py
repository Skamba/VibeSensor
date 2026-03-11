"""Job status tracking, persistence, state store, and runtime detail collection."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from ..json_types import JsonObject, is_json_object
from .models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState
from .runner import sanitize_log_line

LOGGER = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "/var/lib/vibesensor/update/update_status.json"

_LOG_TAIL_MAX = 200
_LOG_TAIL_TRIM_TO = 100


def _phase_name(phase: UpdatePhase | str) -> str:
    return phase.value if isinstance(phase, UpdatePhase) else phase


class UpdateStatusTracker:
    """Owns update job state, persistence, redaction, and issue reporting."""

    __slots__ = ("_redact_secrets", "_state_store", "_status")

    def __init__(
        self,
        *,
        state_store: UpdateStateStore,
        status: UpdateJobStatus | None = None,
    ) -> None:
        self._state_store = state_store
        self._status = status or UpdateJobStatus()
        self._redact_secrets: set[str] = set()

    @property
    def status(self) -> UpdateJobStatus:
        return self._status

    def persist(self) -> None:
        self._state_store.save(self._status)

    def _touch(self, *, phase_changed: bool = False) -> float:
        now = time.time()
        self._status.updated_at = now
        if phase_changed:
            self._status.phase_started_at = now
        return now

    def start_job(self, ssid: str) -> None:
        previous_runtime = dict(self._status.runtime)
        now = time.time()
        self._status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.validating,
            started_at=now,
            phase_started_at=now,
            updated_at=now,
            ssid=ssid,
            last_success_at=self._status.last_success_at,
            runtime=previous_runtime,
        )
        self.persist()

    def transition(self, phase: UpdatePhase) -> None:
        self._status.phase = phase
        self._touch(phase_changed=True)
        self.persist()

    def set_runtime(self, runtime: JsonObject) -> None:
        self._status.runtime = runtime
        self._touch()

    def track_secret(self, secret: str) -> None:
        self._redact_secrets = {secret} if secret else set()

    def clear_secrets(self) -> None:
        self._redact_secrets.clear()

    def redact(self, text: str) -> str:
        redacted = text
        for secret in self._redact_secrets:
            if secret:
                redacted = redacted.replace(secret, "***")
        return redacted

    def redacted_args(self, args: list[str], sensitive_keys: set[str]) -> list[str]:
        redacted: list[str] = []
        hide_next = False
        for raw_arg in args:
            arg = str(raw_arg)
            if hide_next:
                redacted.append("***")
                hide_next = False
                continue
            if arg.lower() in sensitive_keys:
                redacted.append(arg)
                hide_next = True
                continue
            if self._redact_secrets and arg in self._redact_secrets:
                redacted.append("***")
                continue
            redacted.append(arg)
        return redacted

    def log(self, msg: str) -> None:
        sanitized = self.redact(sanitize_log_line(msg))
        log_tail = self._status.log_tail
        log_tail.append(sanitized)
        if len(log_tail) > _LOG_TAIL_MAX:
            del log_tail[:-_LOG_TAIL_TRIM_TO]
        self._touch()

    def add_issue(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self._status.issues.append(
            UpdateIssue(
                phase=_phase_name(phase),
                message=self.redact(message),
                detail=self.redact(sanitize_log_line(detail)),
            ),
        )
        self._touch()

    def extend_issues(self, issues: list[UpdateIssue]) -> None:
        for issue in issues:
            self._status.issues.append(
                UpdateIssue(
                    phase=issue.phase,
                    message=self.redact(issue.message),
                    detail=self.redact(issue.detail),
                ),
            )
        if issues:
            self._touch()

    def fail(self, phase: UpdatePhase | str, message: str, detail: str = "") -> None:
        self.add_issue(phase, message, detail)
        self._status.state = UpdateState.failed
        self._touch()
        self.persist()

    def mark_interrupted(self, message: str) -> None:
        self._status.state = UpdateState.failed
        self._status.finished_at = time.time()
        self._status.issues.append(UpdateIssue(phase="startup", message=message))
        self._touch()
        self.persist()

    def mark_success(self, message: str | None = None) -> None:
        now = time.time()
        self._status.state = UpdateState.success
        self._status.phase = UpdatePhase.done
        self._status.last_success_at = now
        self._status.exit_code = 0
        self._status.phase_started_at = now
        self._status.updated_at = now
        if message:
            self.log(message)
        self.persist()

    def finish_cleanup(self) -> None:
        now = time.time()
        self._status.finished_at = self._status.finished_at or now
        if self._status.state == UpdateState.running:
            self._status.state = UpdateState.failed
        if self._status.state != UpdateState.failed:
            self._status.phase = UpdatePhase.done
            self._status.phase_started_at = now
        self._status.updated_at = now
        self.persist()


# ---------------------------------------------------------------------------
# Persistent state store
# ---------------------------------------------------------------------------


class UpdateStateStore:
    """Load / save :class:`UpdateJobStatus` to a JSON file.

    Writes are atomic (write-to-temp + ``os.replace``) so a crash mid-write
    never corrupts the file.  Reads tolerate missing or malformed JSON and
    return ``None`` with a logged warning.
    """

    __slots__ = ("_path",)

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(
            path or os.environ.get("VIBESENSOR_UPDATE_STATE_PATH", DEFAULT_STATE_PATH),
        )

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> UpdateJobStatus | None:
        """Load persisted status.  Returns ``None`` if missing or corrupt."""
        if not self._path.is_file():
            return None
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return UpdateJobStatus.from_dict(data)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            LOGGER.warning("Corrupt update state file %s: %s", self._path, exc)
            return None
        except OSError as exc:
            LOGGER.warning("Cannot read update state file %s: %s", self._path, exc)
            return None

    def save(self, status: UpdateJobStatus) -> None:
        """Persist *status* atomically (temp-file + ``os.replace``)."""
        data = status.to_dict()
        payload = json.dumps(data, indent=2, default=str) + "\n"
        tmp: str | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=".update_status_",
                suffix=".tmp",
            )
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            Path(tmp).replace(self._path)
        except OSError as exc:
            LOGGER.warning("Failed to persist update state to %s: %s", self._path, exc)
            if tmp is not None:
                with contextlib.suppress(OSError):
                    Path(tmp).unlink()


# ---------------------------------------------------------------------------
# Runtime detail collection
# ---------------------------------------------------------------------------

UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"
_PACKAGED_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


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


def collect_runtime_details(repo: Path) -> JsonObject:
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
