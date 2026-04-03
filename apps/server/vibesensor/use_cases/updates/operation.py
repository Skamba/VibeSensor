"""Canonical end-to-end update execution boundary."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.release_workflow import UpdateReleaseWorkflow
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSessions
from vibesensor.use_cases.updates.validation import UpdateValidationConfig, validate_prerequisites


class UpdateOperation:
    """Coordinate validation, transport preparation, and release application."""

    __slots__ = (
        "_cancel_requested",
        "_commands",
        "_release_workflow",
        "_tracker",
        "_transport_sessions",
        "_validation_config",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport_sessions: UpdateTransportSessions,
        release_workflow: UpdateReleaseWorkflow,
        cancel_requested: Callable[[], bool],
        validation_config: UpdateValidationConfig,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._transport_sessions = transport_sessions
        self._release_workflow = release_workflow
        self._cancel_requested = cancel_requested
        self._validation_config = validation_config

    async def execute(self, request: UpdateRequest) -> None:
        if not await self._validate(request):
            return
        transport_session = self._transport_sessions.for_request(request)
        if not await transport_session.prepare(request):
            return
        if self._cancelled():
            return
        await self._release_workflow.execute(transport_session)

    async def _validate(self, request: UpdateRequest) -> bool:
        if not await validate_prerequisites(
            commands=self._commands,
            tracker=self._tracker,
            config=self._validation_config,
            request=request,
        ):
            return False
        return not self._cancelled()

    def _cancelled(self) -> bool:
        return self._cancel_requested()
