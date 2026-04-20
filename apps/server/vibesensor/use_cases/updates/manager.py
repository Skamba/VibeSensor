"""Canonical update-job runtime and public API."""

from __future__ import annotations

import asyncio

from opentelemetry.trace import SpanKind

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.shared.tracing import mark_span_error, start_span
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import (
    UpdateStatusTracker,
    UpdateTerminalStateReporter,
)
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader
from vibesensor.use_cases.updates.workflow import UpdateWorkflow


class UpdateManager:
    """Own update start/cancel/recovery and the managed workflow task lifecycle."""

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        reporter: UpdateTerminalStateReporter,
        workflow: UpdateWorkflow,
        startup_recovery: UpdateStartupRecoveryCoordinator,
        usb_status_service: UsbInternetStatusReader,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._status = status
        self._reporter = reporter
        self._workflow = workflow
        self._startup_recovery = startup_recovery
        self._usb_status_service = usb_status_service
        self._timeout_s = timeout_s
        self._task_name = task_name
        self._task: asyncio.Task[None] | None = None

    @property
    def status(self) -> UpdateJobStatus:
        return self._status.status

    @property
    def job_task(self) -> asyncio.Task[None] | None:
        return self._task

    async def get_usb_internet_status(self) -> UsbInternetStatus:
        return await self._usb_status_service.snapshot(activate=True)

    def start(
        self,
        ssid: str | None = None,
        password: str = "",
        *,
        transport: UpdateTransport = UpdateTransport.wifi,
    ) -> None:
        request = validate_update_request(ssid, password, transport=transport)
        if self._task is not None and not self._task.done():
            raise UpdateError("Update already in progress", status="conflict")
        self._status.start_job(request)
        self._status.track_secret(request.password)
        self._task = asyncio.get_running_loop().create_task(
            self._run_managed_workflow(request),
            name=self._task_name,
        )

    def cancel(self) -> bool:
        if self._task is None or self._task.done():
            return False
        self._task.cancel()
        return True

    async def startup_recover(self) -> None:
        with start_span(__name__, "update.startup_recover", kind=SpanKind.INTERNAL) as span:
            try:
                await self._startup_recovery.recover()
            except asyncio.CancelledError:
                span.set_attribute("vibesensor.cancelled", True)
                raise
            except Exception as exc:
                mark_span_error(span, exc)
                raise

    async def _run_managed_workflow(self, request: UpdateRequest) -> None:
        with start_span(
            __name__,
            "update.workflow",
            kind=SpanKind.INTERNAL,
            attributes={"vibesensor.transport": request.transport.value},
        ) as span:
            try:
                await asyncio.wait_for(
                    self._workflow.run(request=request),
                    timeout=self._timeout_s,
                )
            except UpdateCleanupError as exc:
                mark_span_error(span, exc)
                self._reporter.fail(exc, default_phase="cleanup")
                raise
            except UpdateError as exc:
                mark_span_error(span, exc)
                self._reporter.fail(exc, default_phase="workflow")
                return
            except TimeoutError as exc:
                mark_span_error(span, exc)
                self._reporter.fail_timeout(timeout_s=self._timeout_s)
            except asyncio.CancelledError:
                span.set_attribute("vibesensor.cancelled", True)
                self._reporter.fail_cancelled()
                raise
            finally:
                span.set_attribute("vibesensor.final_state", self._status.status.state.value)
                self._status.clear_secrets()
                self._status.finish_cleanup()
