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
            workflow_task = asyncio.create_task(
                self._workflow.run(request=request),
                name=f"{self._task_name}-workflow",
            )
            try:
                await asyncio.wait_for(
                    asyncio.shield(workflow_task),
                    timeout=self._timeout_s,
                )
            except UpdateCleanupError as exc:
                mark_span_error(span, exc)
                if str(exc).startswith("Cleanup failed after cancellation:"):
                    self._reporter.fail_cancelled_cleanup_failed(exc)
                    return
                self._reporter.fail_cleanup_failed(exc)
                raise
            except UpdateError as exc:
                mark_span_error(span, exc)
                self._reporter.fail(exc, default_phase="workflow")
                return
            except TimeoutError as exc:
                mark_span_error(span, exc)
                workflow_task.cancel()
                cleanup_error = await _await_cancelled_workflow_cleanup(workflow_task)
                if cleanup_error is not None:
                    mark_span_error(span, cleanup_error)
                    self._reporter.fail_timeout_cleanup_failed(
                        cleanup_error,
                        timeout_s=self._timeout_s,
                    )
                else:
                    self._reporter.fail_timeout(timeout_s=self._timeout_s)
            except asyncio.CancelledError:
                span.set_attribute("vibesensor.cancelled", True)
                workflow_task.cancel()
                cleanup_error = await _await_cancelled_workflow_cleanup(workflow_task)
                if cleanup_error is not None:
                    mark_span_error(span, cleanup_error)
                    self._reporter.fail_cancelled_cleanup_failed(cleanup_error)
                else:
                    self._reporter.fail_cancelled()
                raise
            finally:
                span.set_attribute("vibesensor.final_state", self._status.status.state.value)
                self._status.clear_secrets()
                self._status.finish_cleanup()


async def _await_cancelled_workflow_cleanup(
    workflow_task: asyncio.Task[None],
) -> UpdateCleanupError | None:
    try:
        await workflow_task
    except UpdateCleanupError as exc:
        return exc
    except asyncio.CancelledError:
        return None
    return None
