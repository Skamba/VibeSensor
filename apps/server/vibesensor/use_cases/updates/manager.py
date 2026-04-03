"""Public updater facade over a prebuilt updater runtime."""

from __future__ import annotations

import asyncio

from vibesensor.shared.exceptions import UpdateError
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.runtime import UpdateManagerRuntime

UPDATE_TIMEOUT_S = 600


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
        if not self._runtime.transport_lifecycle.needs_recovery():
            return
        self._runtime.tracker.mark_interrupted("Update interrupted by server restart")
        await self._runtime.transport_lifecycle.recover_interrupted_update()
        self._runtime.tracker.persist()

    async def _run_update(
        self,
        request: UpdateRequest,
    ) -> None:
        try:
            await self._runtime.executor.run(
                workflow_factory=lambda: self._runtime.coordinator_factory().execute(request),
                timeout_s=UPDATE_TIMEOUT_S,
                on_timeout=lambda: self._runtime.lifecycle.handle_timeout(UPDATE_TIMEOUT_S),
                on_cancelled=self._runtime.lifecycle.handle_cancelled,
                cleanup=self._runtime.lifecycle.cleanup_after_update,
            )
        except UpdateError:
            return
