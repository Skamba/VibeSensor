"""Preparation boundary for one update workflow run."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.shared.exceptions import UpdateCleanupError, UpdateError, UpdateTransportError
from vibesensor.use_cases.updates.models import UpdateRequest, UpdateValidationConfig
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.validation import validate_prerequisites

if TYPE_CHECKING:
    from vibesensor.use_cases.updates.transport_sessions import (
        UpdateTransportSession,
        UpdateTransportSessions,
    )

__all__ = [
    "CurrentVersionProvider",
    "PreparedUpdateWorkflow",
    "PreparedTransportSession",
    "UpdatePreparationCoordinator",
    "ValidatedUpdateRequest",
]

CurrentVersionProvider = Callable[[], str]


@dataclass(frozen=True, slots=True)
class PreparedUpdateWorkflow:
    """Validated update workflow state with one resolved transport session."""

    current_version: str
    transport_session: UpdateTransportSession


@dataclass(frozen=True, slots=True)
class ValidatedUpdateRequest:
    """Validated request paired with its canonical transport session."""

    request: UpdateRequest
    transport_session: UpdateTransportSession


@dataclass(frozen=True, slots=True)
class PreparedTransportSession:
    """Transport-prepared request state before runtime version observation."""

    request: UpdateRequest
    transport_session: UpdateTransportSession


class UpdatePreparationCoordinator:
    """Own validation, transport setup, and version resolution before release work."""

    __slots__ = (
        "_commands",
        "_current_version_provider",
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
        validation_config: UpdateValidationConfig,
        current_version_provider: CurrentVersionProvider,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._transport_sessions = transport_sessions
        self._validation_config = validation_config
        self._current_version_provider = current_version_provider

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateWorkflow:
        validated = await self._validate_request(request)
        prepared_transport = await self._prepare_transport(validated)
        return self._observe_current_version(prepared_transport)

    async def _validate_request(self, request: UpdateRequest) -> ValidatedUpdateRequest:
        await validate_prerequisites(
            commands=self._commands,
            tracker=self._tracker,
            config=self._validation_config,
            request=request,
        )
        return ValidatedUpdateRequest(
            request=request,
            transport_session=self._transport_sessions.for_request(request),
        )

    async def _prepare_transport(
        self,
        validated: ValidatedUpdateRequest,
    ) -> PreparedTransportSession:
        try:
            await validated.transport_session.prepare(validated.request)
        except UpdateTransportError:
            await self._abort_preparation(validated.transport_session)
            raise
        return PreparedTransportSession(
            request=validated.request,
            transport_session=validated.transport_session,
        )

    def _observe_current_version(
        self,
        prepared: PreparedTransportSession,
    ) -> PreparedUpdateWorkflow:
        return PreparedUpdateWorkflow(
            current_version=self._current_version_provider(),
            transport_session=prepared.transport_session,
        )

    async def _abort_preparation(self, transport_session: UpdateTransportSession) -> None:
        active_error = sys.exc_info()[1]
        try:
            await transport_session.abort_preparation()
        except (OSError, UpdateError) as exc:
            if active_error is not None:
                active_error.add_note(
                    f"Transport rollback after preparation failure also failed: {exc}",
                )
                return
            raise UpdateCleanupError(
                f"Transport rollback after preparation failure failed: {exc}",
            ) from exc
