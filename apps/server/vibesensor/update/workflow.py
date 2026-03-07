"""Top-level updater workflow orchestration."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .installer import UpdateInstaller
from .models import UpdatePhase, UpdateRequest, UpdateState
from .releases import UpdateReleaseService
from .service_control import UpdateServiceController
from .status import UpdateStatusTracker
from .validation import UpdatePrerequisiteValidator
from .wifi import UpdateWifiController


@dataclass(slots=True)
class UpdateWorkflow:
    tracker: UpdateStatusTracker
    validator: UpdatePrerequisiteValidator
    wifi: UpdateWifiController
    releases: UpdateReleaseService
    installer: UpdateInstaller
    services: UpdateServiceController
    cancel_requested: Callable[[], bool]

    async def run(self, request: UpdateRequest) -> None:
        if not await self.validator.validate(request.ssid):
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.stopping_hotspot)
        if not await self.wifi.stop_hotspot():
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.connecting_wifi)
        if not await self.wifi.connect_uplink(request.ssid, request.password):
            return
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.checking)
        self.tracker.log("Checking for available updates...")
        from vibesensor import __version__ as current_version

        release_check = await self.releases.check_for_update(current_version)
        if release_check.failed:
            return
        if release_check.release is None:
            self.tracker.log(f"Already up-to-date (version={current_version})")
            await self.installer.refresh_esp_firmware(pinned_tag=release_check.latest_tag)
            if self.cancel_requested():
                return
            await self._complete_success("No server update needed; ESP firmware checked")
            return

        self.tracker.log(f"Update available: {current_version} → {release_check.release.version}")
        if self.cancel_requested():
            return

        self.tracker.transition(UpdatePhase.downloading)
        self.tracker.log(f"Downloading release {release_check.release.tag}...")
        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await self.releases.download(release_check.release, staging_dir)
            if wheel_path is None:
                return
            self.tracker.log(
                "Downloaded "
                f"{wheel_path.name} "
                f"(sha256={getattr(release_check.release, 'sha256', '')})"
            )
            if not await self.releases.verify_download(release_check.release, wheel_path):
                return
            await self.installer.refresh_esp_firmware(pinned_tag=release_check.release.tag)
            if self.cancel_requested():
                return

            self.tracker.transition(UpdatePhase.installing)
            self.tracker.log("Installing update...")
            rollback_ok = await self.installer.snapshot_for_rollback()
            if not rollback_ok:
                self.tracker.log("WARNING: Could not create rollback snapshot; proceeding anyway")
            if not await self.installer.install_release(
                wheel_path,
                str(release_check.release.version),
            ):
                return
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        if self.cancel_requested():
            return
        await self._complete_success("Update completed successfully")
        await self.services.ensure_service_contracts_env()
        if await self.services.schedule_restart():
            return
        self.tracker.add_issue(
            "done",
            "Backend restart was not scheduled automatically",
            "Run 'sudo systemctl restart vibesensor.service' manually",
        )
        self.tracker.log("Automatic backend restart scheduling failed")

    async def _complete_success(self, message: str) -> None:
        self.tracker.transition(UpdatePhase.restoring_hotspot)
        self.tracker.log("Restoring hotspot...")
        restored = await self.wifi.restore_hotspot()
        if not restored:
            self.tracker.status.state = UpdateState.failed
            self.tracker.persist()
            return
        self.tracker.mark_success(message)
