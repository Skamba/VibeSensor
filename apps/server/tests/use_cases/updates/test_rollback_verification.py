from __future__ import annotations

from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.use_cases.updates.models import UpdateRuntimeDetails
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotMetadata
from vibesensor.use_cases.updates.rollback_verification import (
    ROLLBACK_CONFIG_MISSING,
    ROLLBACK_SERVICE_UNHEALTHY,
    ROLLBACK_SMOKE_FAILED,
    ROLLBACK_STATIC_MISMATCH,
    RollbackDeploymentVerifier,
    RollbackVerificationConfig,
)


def _metadata(config_path: Path) -> RollbackSnapshotMetadata:
    return RollbackSnapshotMetadata(
        version="2026.5.1",
        sha256="a" * 64,
        config_path=str(config_path),
        repo_path=str(config_path.parent),
        static_assets_hash="assets-a",
        static_build_source_hash="source-a",
        static_build_commit="commit-a",
        assets_verified=True,
        has_packaged_static=True,
    )


def _runtime(**overrides: object) -> UpdateRuntimeDetails:
    values = {
        "version": "2026.5.1",
        "static_assets_hash": "assets-a",
        "static_build_source_hash": "source-a",
        "static_build_commit": "commit-a",
        "assets_verified": True,
        "has_packaged_static": True,
    }
    values.update(overrides)
    return UpdateRuntimeDetails(**values)


@pytest.mark.asyncio
async def test_rollback_verifier_runs_smoke_after_runtime_identity_matches(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.pi.yaml"
    config_path.write_text("server:\n  host: 127.0.0.1\n", encoding="utf-8")
    status = build_update_status_harness(tmp_path / "update_status.json")
    smoke_calls: list[tuple[Path, str, int, float]] = []

    def smoke_runner(
        source_config: Path,
        *,
        host: str,
        port: int,
        startup_timeout_s: float,
    ) -> None:
        smoke_calls.append((source_config, host, port, startup_timeout_s))

    verifier = RollbackDeploymentVerifier(
        status=status,
        config=RollbackVerificationConfig(
            repo=tmp_path,
            source_config=config_path,
            smoke_port=18123,
            smoke_timeout_s=3.0,
        ),
        runtime_collector=lambda repo: _runtime(),
        smoke_runner=smoke_runner,
    )

    assert await verifier.verify(_metadata(config_path)) is True

    assert smoke_calls == [(config_path, "127.0.0.1", 18123, 3.0)]
    assert status.status.issues == []
    assert "Rollback deployment verified" in status.status.log_tail


@pytest.mark.asyncio
async def test_rollback_verifier_reports_smoke_failure(tmp_path: Path) -> None:
    config_path = tmp_path / "config.pi.yaml"
    config_path.write_text("server:\n  host: 127.0.0.1\n", encoding="utf-8")
    status = build_update_status_harness(tmp_path / "update_status.json")

    def smoke_runner(*args: object, **kwargs: object) -> None:
        raise RuntimeError("health endpoint never became ready")

    verifier = RollbackDeploymentVerifier(
        status=status,
        config=RollbackVerificationConfig(repo=tmp_path, source_config=config_path),
        runtime_collector=lambda repo: _runtime(),
        smoke_runner=smoke_runner,
    )

    assert await verifier.verify(_metadata(config_path)) is False

    assert status.status.issues[-1].message == ROLLBACK_SMOKE_FAILED
    assert "health endpoint never became ready" in status.status.issues[-1].detail


@pytest.mark.asyncio
async def test_rollback_verifier_reports_static_and_version_mismatch(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.pi.yaml"
    config_path.write_text("server:\n  host: 127.0.0.1\n", encoding="utf-8")
    status = build_update_status_harness(tmp_path / "update_status.json")

    verifier = RollbackDeploymentVerifier(
        status=status,
        config=RollbackVerificationConfig(repo=tmp_path, source_config=config_path),
        runtime_collector=lambda repo: _runtime(
            version="2026.5.2",
            static_assets_hash="assets-b",
        ),
        smoke_runner=lambda *args, **kwargs: None,
    )

    assert await verifier.verify(_metadata(config_path)) is False

    messages = [issue.message for issue in status.status.issues]
    assert ROLLBACK_SERVICE_UNHEALTHY in messages
    assert ROLLBACK_STATIC_MISMATCH in messages


@pytest.mark.asyncio
async def test_rollback_verifier_requires_recorded_or_fallback_config(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "update_status.json")
    verifier = RollbackDeploymentVerifier(
        status=status,
        config=RollbackVerificationConfig(repo=tmp_path, source_config=None),
        runtime_collector=lambda repo: _runtime(),
        smoke_runner=lambda *args, **kwargs: None,
    )
    metadata = RollbackSnapshotMetadata(version="2026.5.1", sha256="a" * 64)

    assert await verifier.verify(metadata) is False

    assert status.status.issues[-1].message == ROLLBACK_CONFIG_MISSING
