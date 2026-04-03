"""Public updater facade over the canonical updater workflow runner."""

from __future__ import annotations

import asyncio

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.runtime import UpdateManagerRuntime


class UpdateManager:
    """Public update API used by routes and runtime lifecycle."""

    def __init__(
        self,
        *,
        runtime: UpdateManagerRuntime,
    ) -> None:
        self._runtime = runtime

    @property
    def status(self) -> UpdateJobStatus:
        return self._runtime.tracker.status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._runtime.workflow_runner.job_task

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
        self._runtime.workflow_runner.start(
            request=request,
            workflow=lambda context: self._runtime.workflow.run(
                context=context,
                request=request,
            ),
        )

    def cancel(self) -> bool:
        return self._runtime.workflow_runner.cancel()

    async def startup_recover(self) -> None:
        await self._runtime.startup_recovery.recover()
