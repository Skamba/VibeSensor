"""Public updater facade over the updater runtime composition."""

from __future__ import annotations

import asyncio

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.runner import CommandRunner
from vibesensor.use_cases.updates.runtime import build_update_manager_runtime
from vibesensor.use_cases.updates.status import UpdateStateStore
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader

UPDATE_TIMEOUT_S = 600


class UpdateManager:
    """Public update API used by routes and runtime lifecycle."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        repo_path: str | None = None,
        ap_con_name: str = "VibeSensor-AP",
        wifi_ifname: str = "wlan0",
        rollback_dir: str | None = None,
        state_store: UpdateStateStore | None = None,
        usb_internet_service: UsbInternetStatusReader | None = None,
    ) -> None:
        self._runtime = build_update_manager_runtime(
            runner=runner,
            repo_path=repo_path,
            ap_con_name=ap_con_name,
            wifi_ifname=wifi_ifname,
            rollback_dir=rollback_dir,
            state_store=state_store,
            usb_internet_service=usb_internet_service,
        )

    @property
    def status(self) -> UpdateJobStatus:
        return self._runtime.tracker.status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._runtime.executor.job_task

    async def get_usb_internet_status(self) -> UsbInternetStatus:
        return await self._runtime.usb_status_service.snapshot(activate=True)

    def start(
        self,
        ssid: str | None = None,
        password: str = "",
        *,
        transport: UpdateTransport = UpdateTransport.wifi,
    ) -> None:
        request = validate_update_request(ssid, password, transport=transport)
        self._runtime.executor.start(
            lambda: self._run_update(request),
            before_start=lambda: self._runtime.lifecycle.prepare_start(request),
        )

    def cancel(self) -> bool:
        return self._runtime.executor.cancel()

    async def startup_recover(self) -> None:
        if self._runtime.recovery.needs_recovery():
            await self._runtime.recovery.recover()

    async def _run_update(
        self,
        request_or_ssid: UpdateRequest | str,
        password: str | None = None,
    ) -> None:
        await self._runtime.executor.run(
            workflow_factory=lambda: self._run_update_inner(request_or_ssid, password),
            timeout_s=UPDATE_TIMEOUT_S,
            on_timeout=lambda: self._runtime.lifecycle.handle_timeout(UPDATE_TIMEOUT_S),
            on_cancelled=self._runtime.lifecycle.handle_cancelled,
            on_unexpected=self._runtime.lifecycle.handle_unexpected,
            cleanup=self._runtime.lifecycle.cleanup_after_update,
            on_cleanup_error=self._runtime.lifecycle.handle_cleanup_error,
        )

    async def _run_update_inner(
        self,
        request_or_ssid: UpdateRequest | str,
        password: str | None = None,
    ) -> None:
        request = (
            request_or_ssid
            if isinstance(request_or_ssid, UpdateRequest)
            else UpdateRequest(
                transport=UpdateTransport.wifi,
                ssid=request_or_ssid,
                password=password or "",
            )
        )
        operation = self._runtime.operation_factory()
        await operation.execute(request)
