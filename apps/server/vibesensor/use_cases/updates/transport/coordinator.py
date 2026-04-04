"""Canonical transport lifecycle coordination for updater workflows."""

from __future__ import annotations

import logging

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.lifecycles import (
    PreparedUpdateTransport,
    UpdateTransportLifecycle,
    UpdateTransportLifecycles,
)

__all__ = ["UpdateTransportCoordinator"]


class UpdateTransportCoordinator:
    """Resolve transport lifecycles, return prepared handles, and wrap cleanup errors."""

    __slots__ = ("_lifecycles", "_logger", "_status")

    def __init__(
        self,
        *,
        lifecycles: UpdateTransportLifecycles,
        status: UpdateStatusTracker,
        logger: logging.Logger,
    ) -> None:
        self._lifecycles = lifecycles
        self._status = status
        self._logger = logger

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateTransport:
        lifecycle = self._lifecycles.for_request(request)
        try:
            return await lifecycle.prepare(request)
        except UpdateTransportError as exc:
            await self._abort_preparation(
                lifecycle,
                prior_error=exc,
            )
            raise

    async def cleanup_after_update(
        self,
        prepared_transport: PreparedUpdateTransport | None,
    ) -> None:
        if prepared_transport is None:
            return
        try:
            await prepared_transport.cleanup_after_update()
        except (OSError, UpdateError) as exc:
            self._status.fail("cleanup", "Transport cleanup failed", str(exc))
            self._logger.exception("update: transport cleanup error")
            raise UpdateCleanupError(f"Transport cleanup failed: {exc}") from exc

    async def recover_interrupted(self, status: UpdateJobStatus) -> None:
        await self._lifecycles.for_status(status).recover_interrupted_update(status)

    async def _abort_preparation(
        self,
        lifecycle: UpdateTransportLifecycle,
        *,
        prior_error: BaseException | None,
    ) -> None:
        try:
            await lifecycle.abort_preparation()
        except (OSError, UpdateError) as exc:
            if prior_error is not None:
                prior_error.add_note(
                    f"Transport rollback after preparation failure also failed: {exc}",
                )
                return
            raise UpdateCleanupError(
                f"Transport rollback after preparation failure failed: {exc}",
            ) from exc
