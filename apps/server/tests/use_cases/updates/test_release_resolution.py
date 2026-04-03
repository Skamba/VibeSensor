from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.release_resolution import (
    ServerReleaseResolver,
    UpdateReleaseCheck,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


@pytest.mark.asyncio
async def test_resolve_maps_update_check_fields(tmp_path: Path) -> None:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    resolver = ServerReleaseResolver(tracker=tracker, rollback_dir=tmp_path / "rollback")
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")

    with patch(
        "vibesensor.use_cases.updates.release_resolution.check_for_update",
        new=AsyncMock(
            return_value=UpdateReleaseCheck(
                release=release,
                latest_tag="server-v2026.4.4",
            ),
        ),
    ):
        resolution = await resolver.resolve("2026.4.3")

    assert resolution.current_version == "2026.4.3"
    assert resolution.release is release
    assert resolution.latest_tag == "server-v2026.4.4"
    assert resolution.update_available is True


@pytest.mark.asyncio
async def test_resolve_propagates_release_check_failure(tmp_path: Path) -> None:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    resolver = ServerReleaseResolver(tracker=tracker, rollback_dir=tmp_path / "rollback")

    with patch(
        "vibesensor.use_cases.updates.release_resolution.check_for_update",
        new=AsyncMock(side_effect=UpdateReleaseError("rate limited")),
    ):
        with pytest.raises(UpdateReleaseError, match="rate limited"):
            await resolver.resolve("2026.4.3")
