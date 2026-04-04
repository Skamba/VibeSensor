from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from test_support.update_status import UpdateStatusHarness, build_update_status_harness

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.models import UpdatePhase, UpdateRequest, UpdateTransport
from vibesensor.use_cases.updates.release_staging import ServerReleaseStager


def _seed_release_ready_state(tracker: UpdateStatusHarness) -> None:
    tracker.start_job(
        UpdateRequest(
            transport=UpdateTransport.usb_internet,
            ssid=None,
            password="",
        )
    )
    tracker.transition(UpdatePhase.connecting_usb_internet)
    tracker.transition(UpdatePhase.checking)


@pytest.mark.asyncio
async def test_stage_yields_staged_release_and_cleans_temp_dir(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    tracker = status.tracker
    _seed_release_ready_state(tracker)
    stager = ServerReleaseStager(
        status=tracker,
        rollback_dir=tmp_path / "rollback",
    )
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="")
    staged_path: Path | None = None

    async def _download_release(_release: object, staging_dir: Path) -> Path:
        nonlocal staged_path
        staged_path = staging_dir / "release.whl"
        staged_path.write_text("wheel", encoding="utf-8")
        return staged_path

    with (
        patch.object(
            ServerReleaseStager,
            "_download_release",
            new=AsyncMock(side_effect=_download_release),
        ),
        patch.object(
            ServerReleaseStager,
            "_verify_download",
            new=AsyncMock(return_value=None),
        ),
    ):
        async with stager.stage(release) as staged:
            assert staged is not None
            assert staged.release is release
            assert staged_path is not None
            assert staged.wheel_path == staged_path

    assert staged_path is not None
    assert staged_path.parent.exists() is False


@pytest.mark.asyncio
async def test_stage_returns_none_when_verification_fails(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    tracker = status.tracker
    _seed_release_ready_state(tracker)
    stager = ServerReleaseStager(
        status=tracker,
        rollback_dir=tmp_path / "rollback",
    )
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="bad")
    staged_dir: Path | None = None

    async def _download_release(_release: object, staging_dir: Path) -> Path:
        nonlocal staged_dir
        staged_dir = staging_dir
        wheel_path = staging_dir / "release.whl"
        wheel_path.write_text("wheel", encoding="utf-8")
        return wheel_path

    with (
        patch.object(
            ServerReleaseStager,
            "_download_release",
            new=AsyncMock(side_effect=_download_release),
        ),
        patch.object(
            ServerReleaseStager,
            "_verify_download",
            new=AsyncMock(side_effect=UpdateReleaseError("checksum mismatch")),
        ),
        pytest.raises(UpdateReleaseError, match="checksum mismatch"),
    ):
        async with stager.stage(release):
            pytest.fail("stage() should not yield when verification fails")

    assert staged_dir is not None
    assert staged_dir.exists() is False
