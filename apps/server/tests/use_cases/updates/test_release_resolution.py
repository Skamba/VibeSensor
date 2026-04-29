from __future__ import annotations

from types import SimpleNamespace

import pytest

from vibesensor.shared.exceptions import UpdateReleaseError
from vibesensor.use_cases.updates.release_resolution import ServerReleaseResolver


class _StaticFetcher:
    def __init__(self, release: object) -> None:
        self._release = release

    def find_latest_release(self) -> object:
        return self._release


class _FailingFetcher:
    def find_latest_release(self) -> object:
        raise OSError("rate limited")


@pytest.mark.asyncio
async def test_resolve_returns_release_when_latest_version_is_newer() -> None:
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4")
    resolver = ServerReleaseResolver(release_fetcher=_StaticFetcher(release))

    resolution = await resolver.resolve("2026.4.3")

    assert resolution.current_version == "2026.4.3"
    assert resolution.release is release
    assert resolution.latest_tag == ""
    assert resolution.update_available is True


@pytest.mark.asyncio
async def test_resolve_uses_latest_tag_when_no_update_is_available() -> None:
    resolver = ServerReleaseResolver(
        release_fetcher=_StaticFetcher(
            SimpleNamespace(
                tag="server-v2026.4.4",
                version="2026.4.3",
            ),
        ),
    )

    resolution = await resolver.resolve("2026.4.3")

    assert resolution.current_version == "2026.4.3"
    assert resolution.release is None
    assert resolution.latest_tag == "server-v2026.4.4"
    assert resolution.update_available is False


@pytest.mark.asyncio
async def test_resolve_propagates_release_check_failure() -> None:
    resolver = ServerReleaseResolver(release_fetcher=_FailingFetcher())

    with pytest.raises(UpdateReleaseError, match="rate limited"):
        await resolver.resolve("2026.4.3")
