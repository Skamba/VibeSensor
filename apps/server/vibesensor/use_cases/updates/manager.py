"""Canonical update-job runtime and public API."""

from __future__ import annotations

import asyncio

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError
from vibesensor.use_cases.updates.models import (
    UpdateJobStatus,
    UpdateRequest,
    UpdateState,
    UpdateTransport,
    UsbInternetStatus,
    validate_update_request,
)
from vibesensor.use_cases.updates.startup_recovery import UpdateStartupRecoveryCoordinator
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.usb_status import UsbInternetStatusReader
from vibesensor.use_cases.updates.workflow import UpdateWorkflow


class UpdateManager:
    """Own update start/cancel/recovery and the managed workflow task lifecycle."""

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        workflow: UpdateWorkflow,
        startup_recovery: UpdateStartupRecoveryCoordinator,
        usb_status_service: UsbInternetStatusReader,
        timeout_s: float,
        task_name: str = "system-update",
    ) -> None:
        self._status = status
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
        await self._startup_recovery.recover()

    async def _run_managed_workflow(self, request: UpdateRequest) -> None:
        try:
            await asyncio.wait_for(
                self._workflow.run(request=request),
                timeout=self._timeout_s,
            )
        except UpdateCleanupError:
            raise
        except UpdateError as exc:
            if self.status.state is UpdateState.running:
                self._status.fail("workflow", str(exc))
            return
        except TimeoutError:
            self._status.fail(
                "timeout",
                f"Update timed out after {self._timeout_s}s",
                log_message=f"Update timed out after {self._timeout_s}s",
            )
        except asyncio.CancelledError:
            self._status.fail("cancelled", "Update was cancelled", log_message="Update cancelled")
            raise
        finally:
            self._status.clear_secrets()
            self._status.finish_cleanup()
