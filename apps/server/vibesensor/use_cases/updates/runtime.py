"""Runtime composition for the canonical updater manager."""

from __future__ import annotations

import logging

from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.runner import CommandRunner
from vibesensor.use_cases.updates.runtime_services import (
    build_update_runtime_services,
    build_update_workflow,
    resolve_update_runtime_config,
)
from vibesensor.use_cases.updates.status import UpdateStateStore
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader

LOGGER = logging.getLogger(__name__)

UPDATE_TIMEOUT_S = 600


def build_update_manager(
    *,
    runner: CommandRunner | None = None,
    repo_path: str | None = None,
    ap_con_name: str = "VibeSensor-AP",
    wifi_ifname: str = "wlan0",
    rollback_dir: str | None = None,
    state_store: UpdateStateStore | None = None,
    usb_internet_service: UsbInternetStatusReader | None = None,
) -> UpdateManager:
    active_runner = runner or CommandRunner()
    config = resolve_update_runtime_config(
        repo_path=repo_path,
        rollback_dir=rollback_dir,
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    active_state_store = state_store or UpdateStateStore()
    services = build_update_runtime_services(
        runner=active_runner,
        config=config,
        state_store=active_state_store,
        usb_internet_service=usb_internet_service,
        logger=LOGGER,
    )
    workflow = build_update_workflow(
        commands=services.commands,
        status=services.status,
        config=config,
        transport_coordinator=services.transport_coordinator,
        logger=LOGGER,
    )
    return UpdateManager(
        status=services.status,
        usb_status_service=services.usb_status_service,
        startup_recovery=services.startup_recovery,
        workflow=workflow,
        timeout_s=UPDATE_TIMEOUT_S,
    )
