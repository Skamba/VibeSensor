"""Staging downloads the wheel and its Pi wheelhouse, verifies both, and unpacks safely."""

from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.common.exceptions import UpdateCleanupError, UpdateReleaseError
from vibesensor.updates.models import UpdatePhase, UpdateRequest, UpdateTransport
from vibesensor.updates.release_staging import ServerReleaseStager
from vibesensor.updates.releases.models import ReleaseInfo
from vibesensor.updates.status.tracker import UpdateStatusTracker

_WHEEL = b"wheel-bytes"


def _tar(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


_WHEELHOUSE = _tar({"numpy-2.5.3-cp313-cp313-linux_armv7l.whl": b"numpy", "anyio.whl": b"a"})


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _release(**changes: str) -> ReleaseInfo:
    release = ReleaseInfo(
        tag="server-v2026.4.4",
        version="2026.4.4",
        asset_name="vibesensor-2026.4.4-py3-none-any.whl",
        asset_url="https://api.github.com/assets/1",
        sha256=_sha(_WHEEL),
        wheelhouse_name="vibesensor-wheelhouse-2026.4.4-cp313-linux_armv7l.tar",
        wheelhouse_url="https://api.github.com/assets/2",
        wheelhouse_sha256=_sha(_WHEELHOUSE),
    )
    return replace(release, **changes)


class _Fetcher:
    def __init__(self, wheelhouse: bytes = _WHEELHOUSE) -> None:
        self.assets = {
            "https://api.github.com/assets/1": _WHEEL,
            "https://api.github.com/assets/2": wheelhouse,
        }
        self.downloaded: list[str] = []

    def download_asset(self, name: str, url: str, dest_dir: Path) -> Path:
        self.downloaded.append(name)
        path = Path(dest_dir) / name
        path.write_bytes(self.assets[url])
        return path


def _stager(tmp_path: Path, fetcher: _Fetcher) -> tuple[ServerReleaseStager, Path]:
    tracker = build_update_status_harness(tmp_path / "state.json")
    _seed_release_ready_state(tracker)
    staging_parent = tmp_path / ".venv"
    staging_parent.mkdir()
    stager = ServerReleaseStager(
        status=tracker,
        release_fetcher=fetcher,
        staging_parent=staging_parent,
    )
    return stager, staging_parent


def _seed_release_ready_state(tracker: UpdateStatusTracker) -> None:
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
async def test_stage_verifies_both_assets_and_unpacks_the_wheelhouse_on_disk(
    tmp_path: Path,
) -> None:
    fetcher = _Fetcher()
    stager, staging_parent = _stager(tmp_path, fetcher)
    (staging_parent / ".staging-interrupted").mkdir()

    async with stager.stage(_release()) as staged:
        assert staged.wheel_path.read_bytes() == _WHEEL
        assert staged.wheel_path.parent.parent == staging_parent
        assert sorted(p.name for p in staged.wheelhouse_dir.iterdir()) == [
            "anyio.whl",
            "numpy-2.5.3-cp313-cp313-linux_armv7l.whl",
        ]
        assert not (staged.wheel_path.parent / _release().wheelhouse_name).exists()

    assert list(staging_parent.iterdir()) == []


@pytest.mark.asyncio
async def test_stage_rejects_a_release_without_a_wheelhouse(tmp_path: Path) -> None:
    fetcher = _Fetcher()
    stager, _ = _stager(tmp_path, fetcher)

    with pytest.raises(UpdateReleaseError, match="has no dependency wheelhouse") as excinfo:
        async with stager.stage(_release(wheelhouse_name="", wheelhouse_url="")):
            pytest.fail("stage() must not yield")

    assert excinfo.value.phase == UpdatePhase.downloading.value
    assert fetcher.downloaded == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"wheelhouse_sha256": "0" * 64}, "wheelhouse-2026.4.4-cp313-linux_armv7l.tar SHA-256"),
        ({"sha256": "0" * 64}, "vibesensor-2026.4.4-py3-none-any.whl SHA-256 mismatch"),
        ({"wheelhouse_sha256": ""}, "missing a trusted SHA-256 digest"),
    ],
)
@pytest.mark.asyncio
async def test_stage_refuses_unverified_assets_and_cleans_up(
    tmp_path: Path,
    changes: dict[str, str],
    message: str,
) -> None:
    stager, staging_parent = _stager(tmp_path, _Fetcher())

    with pytest.raises(UpdateReleaseError, match=message):
        async with stager.stage(_release(**changes)):
            pytest.fail("stage() must not yield")

    assert list(staging_parent.iterdir()) == []


@pytest.mark.parametrize(
    "entries",
    [
        {"../escape.whl": b"x"},
        {"nested/dir.whl": b"x"},
        {"README.txt": b"x"},
        {},
    ],
)
@pytest.mark.asyncio
async def test_stage_rejects_unsafe_wheelhouse_archives(
    tmp_path: Path,
    entries: dict[str, bytes],
) -> None:
    archive = _tar(entries)
    stager, staging_parent = _stager(tmp_path, _Fetcher(wheelhouse=archive))

    with pytest.raises(UpdateReleaseError, match="Downloaded wheelhouse is invalid"):
        async with stager.stage(_release(wheelhouse_sha256=_sha(archive))):
            pytest.fail("stage() must not yield")

    assert not (tmp_path / "escape.whl").exists()
    assert list(staging_parent.iterdir()) == []


@pytest.mark.asyncio
async def test_stage_raises_cleanup_error_when_cleanup_fails_without_prior_error(
    tmp_path: Path,
) -> None:
    stager, _ = _stager(tmp_path, _Fetcher())

    with (
        patch(
            "vibesensor.updates.release_staging.shutil.rmtree",
            side_effect=OSError("busy"),
        ),
        pytest.raises(UpdateCleanupError, match="Failed to remove staged release directory: busy"),
    ):
        async with stager.stage(_release()):
            pass


@pytest.mark.asyncio
async def test_stage_keeps_prior_error_and_adds_cleanup_note(tmp_path: Path) -> None:
    stager, _ = _stager(tmp_path, _Fetcher())

    with (
        patch(
            "vibesensor.updates.release_staging.shutil.rmtree",
            side_effect=OSError("busy"),
        ),
        pytest.raises(UpdateReleaseError, match="SHA-256 mismatch") as exc_info,
    ):
        async with stager.stage(_release(sha256="0" * 64)):
            pytest.fail("stage() must not yield")

    assert exc_info.value.__notes__ == ["Failed to remove staged release directory: busy"]
