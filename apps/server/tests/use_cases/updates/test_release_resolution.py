from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver


@pytest.mark.asyncio
async def test_resolve_returns_release_without_latest_tag_lookup(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    resolver = ServerReleaseResolver(
        status=status,
        rollback_dir=tmp_path / "rollback",
    )
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    fetcher = MagicMock()
    fetcher.check_update_available.return_value = release

    with patch(
        "vibesensor.use_cases.updates.release_resolution.release_fetcher_factory.build_server_release_fetcher",
        return_value=fetcher,
    ):
        resolution = await resolver.resolve("2026.4.3")

    assert resolution.current_version == "2026.4.3"
    assert resolution.release is release
    assert resolution.latest_tag == ""
    assert resolution.update_available is True
    fetcher.find_latest_release.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_uses_latest_tag_when_no_update_is_available(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    resolver = ServerReleaseResolver(
        status=status,
        rollback_dir=tmp_path / "rollback",
    )
    fetcher = MagicMock()
    fetcher.check_update_available.return_value = None
    fetcher.find_latest_release.return_value = SimpleNamespace(tag="server-v2026.4.4")

    with patch(
        "vibesensor.use_cases.updates.release_resolution.release_fetcher_factory.build_server_release_fetcher",
        return_value=fetcher,
    ):
        resolution = await resolver.resolve("2026.4.3")

    assert resolution.current_version == "2026.4.3"
    assert resolution.release is None
    assert resolution.latest_tag == "server-v2026.4.4"
    assert resolution.update_available is False


@pytest.mark.asyncio
async def test_resolve_propagates_release_check_failure(tmp_path: Path) -> None:
    status = build_update_status_harness(tmp_path / "state.json")
    resolver = ServerReleaseResolver(
        status=status,
        rollback_dir=tmp_path / "rollback",
    )
    fetcher = MagicMock()
    fetcher.check_update_available.side_effect = OSError("rate limited")

    with patch(
        "vibesensor.use_cases.updates.release_resolution.release_fetcher_factory.build_server_release_fetcher",
        return_value=fetcher,
    ):
        with pytest.raises(UpdateReleaseError, match="rate limited"):
            await resolver.resolve("2026.4.3")
