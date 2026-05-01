"""Runtime composition for the canonical updater manager."""

from __future__ import annotations

import logging

from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.releases.release_fetcher import ServerReleaseFetcher
from vibesensor.use_cases.updates.rollback_snapshot import RollbackSnapshotStore
from vibesensor.use_cases.updates.rollback_verification import (
    RollbackDeploymentVerifier,
    RollbackVerificationConfig,
)
from vibesensor.use_cases.updates.runner import CommandRunner
from vibesensor.use_cases.updates.runtime_config import resolve_update_runtime_config
from vibesensor.use_cases.updates.runtime_core import build_update_runtime_core
from vibesensor.use_cases.updates.status import UpdateStateStore
from vibesensor.use_cases.updates.transport.runtime import build_update_transport_runtime
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader
from vibesensor.use_cases.updates.workflow_runtime import build_update_workflow

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
    server_release_fetcher: ServerReleaseFetcher | None = None,
) -> UpdateManager:
    active_runner = runner or CommandRunner()
    config = resolve_update_runtime_config(
        repo_path=repo_path,
        rollback_dir=rollback_dir,
        ap_con_name=ap_con_name,
        wifi_ifname=wifi_ifname,
    )
    active_state_store = state_store or UpdateStateStore()
    core = build_update_runtime_core(
        runner=active_runner,
        repo=config.repo,
        state_store=active_state_store,
    )
    rollback_snapshots = RollbackSnapshotStore(config.rollback_dir, core.status)
    rollback_verifier = RollbackDeploymentVerifier(
        status=core.status,
        config=RollbackVerificationConfig(
            repo=config.repo,
            source_config=config.installer_config.smoke_config_path,
        ),
    )
    transport = build_update_transport_runtime(
        runner=active_runner,
        commands=core.commands,
        status=core.status,
        reporter=core.reporter,
        rollback_snapshots=rollback_snapshots,
        rollback_verifier=rollback_verifier,
        wifi_config=config.wifi_config,
        usb_internet_service=usb_internet_service,
        logger=LOGGER,
    )
    workflow = build_update_workflow(
        core=core,
        config=config,
        transport=transport,
        logger=LOGGER,
        server_release_fetcher=server_release_fetcher,
    )
    return UpdateManager(
        status=core.status,
        reporter=core.reporter,
        usb_status_service=transport.usb_status_service,
        startup_recovery=transport.startup_recovery,
        workflow=workflow,
        timeout_s=UPDATE_TIMEOUT_S,
    )
