from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vibesensor.use_cases.updates.release_application import UpdateReleaseApplication
from vibesensor.use_cases.updates.releases import UpdateReleaseCheck
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker


class _TransportSession:
    def __init__(self) -> None:
        self.complete_success = AsyncMock(return_value=True)


def _build_application(
    tmp_path: Path,
    *,
    cancel_requested=lambda: False,
) -> tuple[UpdateReleaseApplication, MagicMock, MagicMock, MagicMock]:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    commands = MagicMock()
    commands.run = AsyncMock(return_value=(0, "", ""))
    installer = MagicMock()
    installer.snapshot_for_rollback = AsyncMock(return_value=True)
    installer.install_release = AsyncMock(return_value=True)
    firmware_refresher = MagicMock()
    firmware_refresher.refresh_esp_firmware = AsyncMock()
    application = UpdateReleaseApplication(
        tracker=tracker,
        commands=commands,
        installer=installer,
        firmware_refresher=firmware_refresher,
        cancel_requested=cancel_requested,
        rollback_dir=tmp_path / "rollback",
        service_name="vibesensor.service",
        restart_unit="vibesensor-post-update-restart",
    )
    return application, commands, installer, firmware_refresher


@pytest.mark.asyncio
async def test_execute_marks_success_through_transport_when_already_up_to_date(
    tmp_path: Path,
) -> None:
    application, commands, installer, firmware_refresher = _build_application(tmp_path)
    session = _TransportSession()

    with (
        patch("vibesensor.__version__", "2026.4.3"),
        patch(
            "vibesensor.use_cases.updates.release_application.check_for_update",
            new=AsyncMock(
                return_value=UpdateReleaseCheck(
                    release=None,
                    latest_tag="server-v2026.4.3",
                ),
            ),
        ),
    ):
        await application.execute(session)

    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.3",
    )
    session.complete_success.assert_awaited_once_with(
        "No server update needed; ESP firmware checked",
    )
    installer.snapshot_for_rollback.assert_not_awaited()
    commands.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_downloads_and_installs_before_transport_success(tmp_path: Path) -> None:
    application, commands, installer, firmware_refresher = _build_application(tmp_path)
    session = _TransportSession()
    wheel_path = tmp_path / "release.whl"
    wheel_path.write_text("wheel", encoding="utf-8")
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="")

    with (
        patch("vibesensor.__version__", "2026.4.3"),
        patch(
            "vibesensor.use_cases.updates.release_application.check_for_update",
            new=AsyncMock(return_value=UpdateReleaseCheck(release=release)),
        ),
        patch(
            "vibesensor.use_cases.updates.release_application.download_release",
            new=AsyncMock(return_value=wheel_path),
        ),
        patch(
            "vibesensor.use_cases.updates.release_application.verify_download",
            new=AsyncMock(return_value=True),
        ),
    ):
        await application.execute(session)

    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.4",
    )
    installer.snapshot_for_rollback.assert_awaited_once_with()
    installer.install_release.assert_awaited_once_with(wheel_path, "2026.4.4")
    session.complete_success.assert_awaited_once_with("Update completed successfully")
    commands.run.assert_awaited()


@pytest.mark.asyncio
async def test_execute_does_not_schedule_restart_when_transport_finalize_fails(
    tmp_path: Path,
) -> None:
    application, commands, installer, firmware_refresher = _build_application(tmp_path)
    session = _TransportSession()
    session.complete_success.return_value = False
    wheel_path = tmp_path / "release.whl"
    wheel_path.write_text("wheel", encoding="utf-8")
    release = SimpleNamespace(tag="server-v2026.4.4", version="2026.4.4", sha256="")

    with (
        patch("vibesensor.__version__", "2026.4.3"),
        patch(
            "vibesensor.use_cases.updates.release_application.check_for_update",
            new=AsyncMock(return_value=UpdateReleaseCheck(release=release)),
        ),
        patch(
            "vibesensor.use_cases.updates.release_application.download_release",
            new=AsyncMock(return_value=wheel_path),
        ),
        patch(
            "vibesensor.use_cases.updates.release_application.verify_download",
            new=AsyncMock(return_value=True),
        ),
    ):
        await application.execute(session)

    firmware_refresher.refresh_esp_firmware.assert_awaited_once_with(
        pinned_tag="server-v2026.4.4",
    )
    installer.snapshot_for_rollback.assert_awaited_once_with()
    installer.install_release.assert_awaited_once_with(wheel_path, "2026.4.4")
    session.complete_success.assert_awaited_once_with("Update completed successfully")
    commands.run.assert_not_awaited()
