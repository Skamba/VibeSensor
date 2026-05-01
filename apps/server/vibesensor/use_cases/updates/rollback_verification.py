"""Post-rollback deployment verification."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdateRuntimeDetails
from vibesensor.use_cases.updates.releases.release_validation import run_server_smoke
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotMetadata
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.status.runtime_details import collect_runtime_details

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
