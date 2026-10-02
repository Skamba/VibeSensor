"""Rollback snapshot capture, restore, and post-restore verification.

One module owns the whole rollback concern for updater workflows:

- ``RollbackSnapshotStore`` persists the canonical rollback wheel plus its
  metadata sidecar (atomic writes, promotion/undo of a replaced wheel).
- ``RollbackDeploymentVerifier`` checks that a restored deployment matches the
  snapshot identity and still boots (smoke test).
- ``UpdateRollback`` captures the current server wheel before an install,
  reinstalls the snapshot after a failed install, and re-verifies an
  interrupted install after a server restart.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import msgspec

from vibesensor.updates.artifact_validation import (
    WheelArtifactValidator,
    sha256_file,
    wheel_metadata_validation_errors,
)
from vibesensor.updates.models import UpdateRuntimeDetails
from vibesensor.updates.releases.release_validation import run_server_smoke
from vibesensor.updates.runner import UpdateCommandExecutor
from vibesensor.updates.status.runtime_details import collect_runtime_details
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.venv_paths import reinstall_python_executable
from vibesensor.updates.wheel_installation import WheelInstallExecutor

__all__ = [
    "ROLLBACK_CONFIG_MISSING",
    "ROLLBACK_SERVICE_UNHEALTHY",
    "ROLLBACK_SMOKE_FAILED",
    "ROLLBACK_STATIC_MISMATCH",
    "RollbackDeploymentVerifier",
    "RollbackSnapshot",
    "RollbackSnapshotMetadata",
    "RollbackSnapshotStore",
    "RollbackVerificationConfig",
    "UpdateRollback",
]

_ROLLBACK_METADATA_FILE = "rollback_snapshot.json"
_ROLLBACK_WHEEL_FILE = "rollback_snapshot.whl"
_ROLLBACK_BACKUP_WHEEL_FILE = ".rollback_snapshot.previous.whl"


class _RollbackSnapshotMetadataRecord(msgspec.Struct, kw_only=True, frozen=True):
    version: str = ""
    sha256: str = ""
    config_path: str = ""
    repo_path: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False


@dataclass(frozen=True, slots=True)
class RollbackSnapshotMetadata:
    version: str
    sha256: str
    config_path: str = ""
    repo_path: str = ""
    static_assets_hash: str = ""
    static_build_source_hash: str = ""
    static_build_commit: str = ""
    assets_verified: bool = False
    has_packaged_static: bool = False


@dataclass(frozen=True, slots=True)
class RollbackSnapshot:
    metadata: RollbackSnapshotMetadata
    wheel_path: Path


@dataclass(frozen=True, slots=True)
class RollbackSnapshotPromotion:
    wheel_path: Path
    backup_path: Path | None
    moved_new_wheel: bool


def _rollback_snapshot_metadata_to_json(metadata: RollbackSnapshotMetadata) -> bytes:
    return (
        msgspec.json.encode(
            _RollbackSnapshotMetadataRecord(
                version=metadata.version,
                sha256=metadata.sha256,
                config_path=metadata.config_path,
                repo_path=metadata.repo_path,
                static_assets_hash=metadata.static_assets_hash,
                static_build_source_hash=metadata.static_build_source_hash,
                static_build_commit=metadata.static_build_commit,
                assets_verified=metadata.assets_verified,
                has_packaged_static=metadata.has_packaged_static,
            )
        )
        + b"\n"
    )


def _rollback_snapshot_metadata_from_json(raw: bytes | str) -> RollbackSnapshotMetadata:
    record = _decode_rollback_snapshot_metadata_record(raw)
    return _rollback_snapshot_metadata_from_record(record)


def _decode_rollback_snapshot_metadata_record(raw: bytes | str) -> _RollbackSnapshotMetadataRecord:
    try:
        return msgspec.json.decode(raw, type=_RollbackSnapshotMetadataRecord)
    except msgspec.ValidationError:
        decoded = msgspec.json.decode(raw)
        if not isinstance(decoded, Mapping):
            raise
        return _rollback_snapshot_metadata_record_from_object(decoded)


def _rollback_snapshot_metadata_record_from_object(
    payload: Mapping[str, object],
) -> _RollbackSnapshotMetadataRecord:
    return _RollbackSnapshotMetadataRecord(
        version=_rollback_snapshot_metadata_text(payload.get("version")),
        sha256=_rollback_snapshot_metadata_text(payload.get("sha256")),
        config_path=_rollback_snapshot_metadata_text(payload.get("config_path")),
        repo_path=_rollback_snapshot_metadata_text(payload.get("repo_path")),
        static_assets_hash=_rollback_snapshot_metadata_text(payload.get("static_assets_hash")),
        static_build_source_hash=_rollback_snapshot_metadata_text(
            payload.get("static_build_source_hash")
        ),
        static_build_commit=_rollback_snapshot_metadata_text(payload.get("static_build_commit")),
        assets_verified=bool(payload.get("assets_verified")),
        has_packaged_static=bool(payload.get("has_packaged_static")),
    )


def _rollback_snapshot_metadata_text(value: object) -> str:
    return str(value or "")


def _rollback_snapshot_metadata_from_record(
    record: _RollbackSnapshotMetadataRecord,
) -> RollbackSnapshotMetadata:
    return RollbackSnapshotMetadata(
        version=record.version,
        sha256=record.sha256,
        config_path=record.config_path,
        repo_path=record.repo_path,
        static_assets_hash=record.static_assets_hash,
        static_build_source_hash=record.static_build_source_hash,
        static_build_commit=record.static_build_commit,
        assets_verified=record.assets_verified,
        has_packaged_static=record.has_packaged_static,
    )


class RollbackSnapshotStore:
    """Persist one canonical rollback snapshot wheel plus its metadata."""

    __slots__ = ("_rollback_dir", "_status")

    def __init__(self, rollback_dir: Path, status: UpdateStatusTracker) -> None:
        self._rollback_dir = rollback_dir
        self._status = status

    def _metadata_path(self) -> Path:
        """Return the canonical JSON metadata path for rollback snapshot state."""

        return self._rollback_dir / _ROLLBACK_METADATA_FILE

    def snapshot_wheel_path(self) -> Path:
        """Return the canonical rollback snapshot wheel path."""

        return self._rollback_dir / _ROLLBACK_WHEEL_FILE

    def write_metadata(self, metadata: RollbackSnapshotMetadata) -> None:
        """Atomically persist rollback metadata alongside stored wheels."""

        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        payload = _rollback_snapshot_metadata_to_json(metadata)
        fd, temp_path_text = tempfile.mkstemp(
            prefix=".rollback_snapshot.",
            suffix=".tmp",
            dir=self._rollback_dir,
        )
        temp_path = Path(temp_path_text)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._metadata_path())
        finally:
            temp_path.unlink(missing_ok=True)

    def replace_snapshot_wheel(self, wheel_path: Path) -> RollbackSnapshotPromotion:
        """Promote *wheel_path* into the canonical rollback snapshot location."""

        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        snapshot_wheel_path = self.snapshot_wheel_path()
        moved_new_wheel = wheel_path != snapshot_wheel_path
        backup_path: Path | None = None
        if moved_new_wheel:
            if snapshot_wheel_path.is_file():
                backup_path = self._rollback_dir / _ROLLBACK_BACKUP_WHEEL_FILE
                backup_path.unlink(missing_ok=True)
                snapshot_wheel_path.replace(backup_path)
            wheel_path.replace(snapshot_wheel_path)
        return RollbackSnapshotPromotion(
            wheel_path=snapshot_wheel_path,
            backup_path=backup_path,
            moved_new_wheel=moved_new_wheel,
        )

    def commit_snapshot_wheel(self, promotion: RollbackSnapshotPromotion) -> None:
        """Finalize a promoted rollback wheel after metadata succeeds."""

        if promotion.backup_path is not None:
            promotion.backup_path.unlink(missing_ok=True)

    def rollback_snapshot_wheel(self, promotion: RollbackSnapshotPromotion) -> None:
        """Undo a promoted rollback wheel after metadata persistence fails."""

        if promotion.backup_path is not None:
            promotion.wheel_path.unlink(missing_ok=True)
            promotion.backup_path.replace(self.snapshot_wheel_path())
            return
        if promotion.moved_new_wheel:
            promotion.wheel_path.unlink(missing_ok=True)

    def remove_snapshot(self) -> None:
        """Delete the current rollback snapshot wheel and metadata when invalidated."""

        self.snapshot_wheel_path().unlink(missing_ok=True)
        self._metadata_path().unlink(missing_ok=True)
        (self._rollback_dir / _ROLLBACK_BACKUP_WHEEL_FILE).unlink(missing_ok=True)

    def load_snapshot(self, *, report_issues: bool = True) -> RollbackSnapshot | None:
        """Load the canonical rollback snapshot, optionally reporting problems."""

        metadata = self._load_metadata(report_issues=report_issues)
        if metadata is None:
            return None
        wheel_path = self.snapshot_wheel_path()
        if not wheel_path.is_file():
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot wheel is missing",
                    str(wheel_path),
                )
            return None
        return RollbackSnapshot(metadata=metadata, wheel_path=wheel_path)

    def _load_metadata(self, *, report_issues: bool) -> RollbackSnapshotMetadata | None:
        metadata_path = self._metadata_path()
        if not metadata_path.is_file():
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is missing",
                    str(metadata_path),
                )
            return None
        try:
            metadata = _rollback_snapshot_metadata_from_json(metadata_path.read_bytes())
        except (msgspec.DecodeError, msgspec.ValidationError, OSError) as exc:
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is unreadable",
                    f"{metadata_path}: {exc}",
                )
            return None
        if not metadata.version or not metadata.sha256:
            if report_issues:
                self._status.add_issue(
                    "installing",
                    "Rollback snapshot metadata is incomplete",
                    f"{metadata_path} is missing version or sha256",
                )
            return None
        return metadata


ROLLBACK_SMOKE_FAILED = "rollback_smoke_failed"
ROLLBACK_STATIC_MISMATCH = "rollback_static_mismatch"
ROLLBACK_SERVICE_UNHEALTHY = "rollback_service_unhealthy"
ROLLBACK_CONFIG_MISSING = "rollback_config_missing"


@dataclass(frozen=True, slots=True)
class RollbackVerificationConfig:
    repo: Path
    source_config: Path | None
    smoke_host: str = "127.0.0.1"
    smoke_port: int = 18082
    smoke_timeout_s: float = 45.0


class RollbackDeploymentVerifier:
    """Verify that a restored rollback deployment is coherent and bootable."""

    __slots__ = ("_config", "_runtime_collector", "_smoke_runner", "_status")

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        config: RollbackVerificationConfig,
        runtime_collector: Callable[[Path], UpdateRuntimeDetails] = collect_runtime_details,
        smoke_runner: Callable[..., None] = run_server_smoke,
    ) -> None:
        self._status = status
        self._config = config
        self._runtime_collector = runtime_collector
        self._smoke_runner = smoke_runner

    async def verify(self, metadata: RollbackSnapshotMetadata) -> bool:
        self._status.log("Verifying rollback deployment...")
        runtime = await asyncio.to_thread(self._runtime_collector, self._config.repo)
        ok = True
        if metadata.version and runtime.version and runtime.version != metadata.version:
            self._status.add_issue(
                "installing",
                ROLLBACK_SERVICE_UNHEALTHY,
                f"expected version {metadata.version}, active version {runtime.version}",
            )
            ok = False
        if not _static_runtime_matches_snapshot(runtime, metadata):
            self._status.add_issue(
                "installing",
                ROLLBACK_STATIC_MISMATCH,
                _static_mismatch_detail(runtime, metadata),
            )
            ok = False
        source_config = _verification_config_path(metadata, self._config.source_config)
        if source_config is None or not source_config.is_file():
            self._status.add_issue(
                "installing",
                ROLLBACK_CONFIG_MISSING,
                str(source_config) if source_config is not None else "no config path recorded",
            )
            return False
        try:
            await asyncio.to_thread(
                self._smoke_runner,
                source_config,
                host=self._config.smoke_host,
                port=self._config.smoke_port,
                startup_timeout_s=self._config.smoke_timeout_s,
            )
        except (OSError, RuntimeError) as exc:
            self._status.add_issue("installing", ROLLBACK_SMOKE_FAILED, str(exc))
            return False
        if ok:
            self._status.log("Rollback deployment verified")
        return ok


def _verification_config_path(
    metadata: RollbackSnapshotMetadata,
    fallback: Path | None,
) -> Path | None:
    if metadata.config_path:
        return Path(metadata.config_path)
    return fallback


def _static_runtime_matches_snapshot(
    runtime: UpdateRuntimeDetails,
    metadata: RollbackSnapshotMetadata,
) -> bool:
    if metadata.has_packaged_static and not runtime.has_packaged_static:
        return False
    if metadata.static_assets_hash and runtime.static_assets_hash != metadata.static_assets_hash:
        return False
    if (
        metadata.static_build_source_hash
        and runtime.static_build_source_hash != metadata.static_build_source_hash
    ):
        return False
    if metadata.static_build_commit and runtime.static_build_commit != metadata.static_build_commit:
        return False
    if metadata.assets_verified and not runtime.assets_verified:
        return False
    return True


def _static_mismatch_detail(
    runtime: UpdateRuntimeDetails,
    metadata: RollbackSnapshotMetadata,
) -> str:
    return (
        "rollback static identity mismatch: "
        f"snapshot_assets={metadata.static_assets_hash or '<unknown>'}, "
        f"active_assets={runtime.static_assets_hash or '<unknown>'}, "
        f"snapshot_source={metadata.static_build_source_hash or '<unknown>'}, "
        f"active_source={runtime.static_build_source_hash or '<unknown>'}, "
        f"snapshot_packaged_static={metadata.has_packaged_static}, "
        f"active_packaged_static={runtime.has_packaged_static}"
    )


class UpdateRollback:
    """Capture, restore, and verify the one canonical rollback snapshot."""

    __slots__ = (
        "_commands",
        "_config_path",
        "_repo",
        "_rollback_dir",
        "_rollback_snapshots",
        "_rollback_verifier",
        "_status",
        "_wheel_install_executor",
        "_wheel_validator",
    )

    def __init__(
        self,
        *,
        commands: UpdateCommandExecutor,
        status: UpdateStatusTracker,
        repo: Path,
        rollback_dir: Path,
        config_path: Path | None,
        wheel_validator: WheelArtifactValidator,
        wheel_install_executor: WheelInstallExecutor,
    ) -> None:
        self._commands = commands
        self._status = status
        self._repo = repo
        self._rollback_dir = rollback_dir
        self._config_path = config_path
        self._wheel_validator = wheel_validator
        self._wheel_install_executor = wheel_install_executor
        self._rollback_snapshots = RollbackSnapshotStore(rollback_dir, status)
        self._rollback_verifier = RollbackDeploymentVerifier(
            status=status,
            config=RollbackVerificationConfig(repo=repo, source_config=config_path),
        )

    def _existing_snapshot_wheel(self, *, current_version: str) -> Path | None:
        snapshot = self._rollback_snapshots.load_snapshot(report_issues=False)
        if snapshot is None:
            return None
        errors = wheel_metadata_validation_errors(
            snapshot.wheel_path,
            expected_name="vibesensor",
            expected_version=current_version,
        )
        if snapshot.metadata.version == current_version and not errors:
            self._status.log("Reusing existing rollback snapshot wheel")
            return snapshot.wheel_path
        if errors:
            self._status.log(
                f"Ignoring existing rollback snapshot wheel: {'; '.join(errors)}",
            )
        return None

    def _select_staged_rollback_wheel(
        self,
        *,
        stage_dir: Path,
        current_version: str,
        source_label: str,
    ) -> Path | None:
        staged_wheels = sorted(stage_dir.glob("vibesensor-*.whl"), reverse=True)
        for rollback_wheel in staged_wheels:
            errors = wheel_metadata_validation_errors(
                rollback_wheel,
                expected_name="vibesensor",
                expected_version=current_version,
            )
            if not errors:
                return rollback_wheel
            self._status.log(
                f"{source_label} produced unusable wheel {rollback_wheel.name}: "
                f"{'; '.join(errors)}",
            )
        self._status.log(
            f"{source_label} did not produce a usable wheel for {current_version}",
        )
        return None

    async def _build_local_rollback_wheel(
        self,
        *,
        current_version: str,
        stage_dir: Path,
        venv_python: str,
    ) -> Path | None:
        package_dir = self._repo / "apps" / "server"
        if not (package_dir / "pyproject.toml").is_file():
            self._status.log(
                f"Local rollback wheel build skipped: {package_dir / 'pyproject.toml'} not found",
            )
            return None
        result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "-w",
                str(stage_dir),
                str(package_dir),
            ],
            phase="installing",
            timeout=60,
            sudo=False,
        )
        if result.returncode != 0:
            self._status.log(
                "Local rollback wheel build failed "
                f"(exit {result.returncode}); falling back to package-index download: "
                f"{result.stderr}",
            )
            return None
        return self._select_staged_rollback_wheel(
            stage_dir=stage_dir,
            current_version=current_version,
            source_label="Local rollback wheel build",
        )

    async def _download_rollback_wheel(
        self,
        *,
        current_version: str,
        stage_dir: Path,
        venv_python: str,
    ) -> Path | None:
        result = await self._commands.run(
            [
                venv_python,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-build-isolation",
                "-d",
                str(stage_dir),
                f"vibesensor=={current_version}",
            ],
            phase="installing",
            timeout=60,
            sudo=False,
        )
        if result.returncode != 0:
            self._status.log(
                f"Package-index rollback download failed (exit {result.returncode}): "
                f"{result.stderr}",
            )
            return None
        return self._select_staged_rollback_wheel(
            stage_dir=stage_dir,
            current_version=current_version,
            source_label="Package-index rollback download",
        )

    def _write_rollback_snapshot(
        self,
        *,
        rollback_wheel: Path,
        current_version: str,
        runtime_details: UpdateRuntimeDetails,
    ) -> bool:
        rollback_sha256 = sha256_file(rollback_wheel)
        promotion = self._rollback_snapshots.replace_snapshot_wheel(rollback_wheel)
        try:
            self._rollback_snapshots.write_metadata(
                RollbackSnapshotMetadata(
                    version=current_version,
                    sha256=rollback_sha256,
                    config_path=str(self._config_path) if self._config_path else "",
                    repo_path=str(self._repo),
                    static_assets_hash=runtime_details.static_assets_hash,
                    static_build_source_hash=runtime_details.static_build_source_hash,
                    static_build_commit=runtime_details.static_build_commit,
                    assets_verified=runtime_details.assets_verified,
                    has_packaged_static=runtime_details.has_packaged_static,
                ),
            )
        except OSError as exc:
            self._rollback_snapshots.rollback_snapshot_wheel(promotion)
            self._status.add_issue(
                "installing",
                "Rollback metadata could not be written",
                str(exc),
            )
            return False
        self._rollback_snapshots.commit_snapshot_wheel(promotion)
        self._status.log(
            "Rollback snapshot created successfully "
            f"(version={current_version}, sha256={rollback_sha256})",
        )
        return True

    async def snapshot_for_rollback(self) -> bool:
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        venv_python = reinstall_python_executable(self._repo)
        from vibesensor import __version__ as current_version

        runtime_details = collect_runtime_details(self._repo)

        self._status.log(f"Creating rollback snapshot (version={current_version})")
        if existing_wheel := self._existing_snapshot_wheel(current_version=current_version):
            return self._write_rollback_snapshot(
                rollback_wheel=existing_wheel,
                current_version=current_version,
                runtime_details=runtime_details,
            )
        with tempfile.TemporaryDirectory(
            prefix="vibesensor-rollback-stage-",
            dir=self._rollback_dir.parent,
        ) as stage_dir_text:
            stage_dir = Path(stage_dir_text)
            rollback_wheel = await self._build_local_rollback_wheel(
                current_version=current_version,
                stage_dir=stage_dir,
                venv_python=venv_python,
            )
            if rollback_wheel is None:
                rollback_wheel = await self._download_rollback_wheel(
                    current_version=current_version,
                    stage_dir=stage_dir,
                    venv_python=venv_python,
                )
            if rollback_wheel is None:
                return False
            return self._write_rollback_snapshot(
                rollback_wheel=rollback_wheel,
                current_version=current_version,
                runtime_details=runtime_details,
            )

    async def rollback(self) -> bool:
        self._status.log("Rolling back to previous version...")
        snapshot = self._rollback_snapshots.load_snapshot()
        if snapshot is None:
            return False
        if not self._wheel_validator.validate_wheel(
            snapshot.wheel_path,
            phase="installing",
            context="Rollback snapshot wheel",
            fatal=False,
            expected_sha256=snapshot.metadata.sha256,
        ):
            return False
        installed = await self._wheel_install_executor.install_rollback_wheel(
            snapshot.wheel_path,
            expected_version=snapshot.metadata.version,
        )
        if not installed:
            return False
        return await self._rollback_verifier.verify(snapshot.metadata)

    async def verify_interrupted_install(self) -> None:
        """Re-verify the restored deployment after an install was interrupted."""

        snapshot = self._rollback_snapshots.load_snapshot(report_issues=False)
        if snapshot is None:
            return
        await self._rollback_verifier.verify(snapshot.metadata)
