from __future__ import annotations

from vibesensor.adapters.http.dependencies import UpdateDeps
from vibesensor.app.config_schema import AppConfig
from vibesensor.use_cases.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.use_cases.updates.runtime import build_update_manager


def build_update_deps(config: AppConfig) -> UpdateDeps:
    """Build the grouped updater and firmware-flash dependencies."""

    return UpdateDeps(
        update_manager=build_update_manager(
            ap_con_name=config.ap.con_name,
            wifi_ifname=config.ap.ifname,
            rollback_dir=str(config.update.rollback_dir),
        ),
        esp_flash_manager=EspFlashManager(),
    )
