"""Canonical transport lifecycle coordination for updater workflows."""

from __future__ import annotations

import logging
import sys

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateJobStatus, UpdateRequest
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import (
    ManagedUpdateTransportSession,
    SetupUpdateTransportSession,
    UpdateTransportSessions,
    ValidatingUpdateTransportSession,
)

__all__ = ["UpdateTransportCoordinator"]


class UpdateTransportCoordinator:
    """Resolve and drive transport lifecycle side effects through one boundary."""

    __slots__ = ("_logger", "_sessions", "_status")

    def __init__(
        self,
        *,
        sessions: UpdateTransportSessions,
        status: UpdateStatusTracker,
        logger: logging.Logger,
    ) -> None:
        self._sessions = sessions
        self._status = status
        self._logger = logger

    async def prepare(self, request: UpdateRequest) -> ManagedUpdateTransportSession:
        session = self._sessions.for_request(request)
        try:
            if isinstance(session, SetupUpdateTransportSession):
                await session.prepare(request)
            else:
                assert isinstance(session, ValidatingUpdateTransportSession)  # noqa: S101
                await session.validate(request)
        except UpdateTransportError:
            if isinstance(session, SetupUpdateTransportSession):
                await self._abort_preparation(session)
            raise
        return session

    async def complete_success(
        self,
        transport_session: ManagedUpdateTransportSession,
        *,
        message: str,
    ) -> None:
        await transport_session.complete_success(message)

    async def cleanup_after_update(
        self,
        transport_session: ManagedUpdateTransportSession | None,
    ) -> None:
        if transport_session is None or not isinstance(
            transport_session,
            SetupUpdateTransportSession,
        ):
            return
        try:
            await transport_session.cleanup_after_update()
        except (OSError, UpdateError) as exc:
            self._status.fail("cleanup", "Transport cleanup failed", str(exc))
            self._logger.exception("update: transport cleanup error")
            raise UpdateCleanupError(f"Transport cleanup failed: {exc}") from exc

    async def recover_interrupted(self, status: UpdateJobStatus) -> None:
        transport_session = self._sessions.for_status(status)
        if isinstance(transport_session, SetupUpdateTransportSession):
            await transport_session.recover_interrupted_update()

    async def _abort_preparation(self, session: SetupUpdateTransportSession) -> None:
        active_error = sys.exc_info()[1]
        try:
            await session.abort_preparation()
        except (OSError, UpdateError) as exc:
            if active_error is not None:
                active_error.add_note(
                    f"Transport rollback after preparation failure also failed: {exc}",
                )
                return
            raise UpdateCleanupError(
                f"Transport rollback after preparation failure failed: {exc}",
            ) from exc
