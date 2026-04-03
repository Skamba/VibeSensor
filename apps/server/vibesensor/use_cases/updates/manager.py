"""Public updater facade over the canonical updater workflow runner."""

from __future__ import annotations

import asyncio

from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.runtime import UpdateManagerRuntime
from vibesensor.use_cases.updates.workflow_runner import UpdateWorkflowContext


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
            workflow=lambda context: self._run_update(
                context,
                request,
            ),
        )

    def cancel(self) -> bool:
        return self._runtime.workflow_runner.cancel()

    async def startup_recover(self) -> None:
        status = self._runtime.tracker.status
        if status.state != UpdateState.running or status.finished_at is not None:
            return
        self._runtime.tracker.mark_interrupted("Update interrupted by server restart")
        await (
            self._runtime.build_transport_sessions()
            .for_transport(
                status.transport,
            )
            .recover_interrupted_update()
        )
        self._runtime.tracker.persist()

    async def _run_update(
        self,
        context: UpdateWorkflowContext,
        request: UpdateRequest,
    ) -> None:
        run_runtime = self._runtime.build_run_runtime()
        prepared = await run_runtime.preparation.prepare(request)
        context.transport_session = prepared.transport_session
        planned = await run_runtime.release_planner.plan(prepared)
        await run_runtime.workflow_executor.execute(planned)
