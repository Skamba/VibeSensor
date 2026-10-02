"""Public updater API: start/cancel an update job and supervise its task."""

from __future__ import annotations

import asyncio

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.job import UpdateJob
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.status.tracker import UpdateStatusTracker
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusService


class UpdateManager:
    """Own update start/cancel/recovery and the supervised update-job task lifecycle."""

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        job: UpdateJob,
        usb_status_service: UsbInternetStatusService,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._status = status
        self._job = job
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
        await self._job.recover_interrupted()

    async def _run_managed_workflow(self, request: UpdateRequest) -> None:
        workflow_task = asyncio.create_task(
            self._job.run(request=request),
            name=f"{self._task_name}-workflow",
        )
        try:
            await asyncio.wait_for(
                asyncio.shield(workflow_task),
                timeout=self._timeout_s,
            )
        except UpdateCleanupError as exc:
            if str(exc).startswith("Cleanup failed after cancellation:"):
                self._status.fail_cancelled_cleanup_failed(exc)
                return
            self._status.fail_cleanup_failed(exc)
            raise
        except UpdateError as exc:
            self._status.fail_from_error(exc, default_phase="workflow")
            return
        except TimeoutError:
            workflow_task.cancel()
            cleanup_error = await _await_cancelled_workflow_cleanup(workflow_task)
            if cleanup_error is not None:
                self._status.fail_timeout_cleanup_failed(
                    cleanup_error,
                    timeout_s=self._timeout_s,
                )
            else:
                self._status.fail_timeout(timeout_s=self._timeout_s)
        except asyncio.CancelledError:
            workflow_task.cancel()
            cleanup_error = await _await_cancelled_workflow_cleanup(workflow_task)
            if cleanup_error is not None:
                self._status.fail_cancelled_cleanup_failed(cleanup_error)
            else:
                self._status.fail_cancelled()
            raise
        finally:
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
