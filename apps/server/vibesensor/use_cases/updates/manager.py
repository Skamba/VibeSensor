"""Public updater facade over a prebuilt updater runtime."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateError
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.runtime import UpdateManagerRuntime

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession

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
        status = self._runtime.tracker.status
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._runtime.tracker.mark_interrupted("Update interrupted by server restart")
        await (
            self._runtime.build_transport_sessions(None)
            .for_transport(
                status.transport,
            )
            .recover_interrupted_update()
        )
        self._runtime.tracker.persist()

    async def _run_update(
        self,
        request: UpdateRequest,
    ) -> None:
        active_session: UpdateTransportSession | None = None
        run_runtime = self._runtime.build_run_runtime()

        async def workflow() -> None:
            nonlocal active_session
            prepared = await run_runtime.preparation.prepare(request)
            active_session = prepared.transport_session
            planned = await run_runtime.release_planner.plan(prepared)
            await run_runtime.workflow_executor.execute(planned)

        try:
            await self._runtime.executor.run(
                workflow_factory=workflow,
                timeout_s=UPDATE_TIMEOUT_S,
                on_timeout=lambda: self._runtime.lifecycle.handle_timeout(UPDATE_TIMEOUT_S),
                on_cancelled=self._runtime.lifecycle.handle_cancelled,
                cleanup=lambda: self._runtime.lifecycle.cleanup_after_update(active_session),
            )
        except UpdateError:
            return
