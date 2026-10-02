from __future__ import annotations

from vibesensor.app.config_schema import AppConfig
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager
from vibesensor.updates.hotspot.constants import HOTSPOT_CON_NAME, HOTSPOT_IFNAME
from vibesensor.updates.runtime import build_update_manager
from vibesensor.web.dependencies import UpdateDeps


def build_update_deps(config: AppConfig) -> UpdateDeps:
    """Build the grouped updater and firmware-flash dependencies."""

    return UpdateDeps(
        update_manager=build_update_manager(
            ap_con_name=HOTSPOT_CON_NAME,
            wifi_ifname=HOTSPOT_IFNAME,
            rollback_dir=str(config.update.rollback_dir),
        ),
        esp_flash_manager=EspFlashManager(),
    )
