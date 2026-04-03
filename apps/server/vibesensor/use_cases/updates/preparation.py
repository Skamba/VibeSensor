"""Preparation boundary for one update workflow run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.use_cases.updates.models import UpdateRequest, UpdateValidationConfig
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport_controller import UpdateTransportController
from vibesensor.use_cases.updates.transport_sessions import UpdateTransportSession
from vibesensor.use_cases.updates.validation import validate_prerequisites

__all__ = [
    "CurrentVersionProvider",
    "PreparedUpdateSession",
    "UpdatePreparationCoordinator",
]

CurrentVersionProvider = Callable[[], str]


@dataclass(frozen=True, slots=True)
class PreparedUpdateSession:
    """Validated update-session inputs ready for release planning and execution."""

    request: UpdateRequest
    current_version: str
    transport_session: UpdateTransportSession


class UpdatePreparationCoordinator:
    """Own validation, transport setup, and version resolution before release work."""

    __slots__ = (
        "_commands",
        "_current_version_provider",
        "_tracker",
        "_transport_controller",
        "_validation_config",
    )

    def __init__(
        self,
        *,
        tracker: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport_controller: UpdateTransportController,
        validation_config: UpdateValidationConfig,
        current_version_provider: CurrentVersionProvider,
    ) -> None:
        self._tracker = tracker
        self._commands = commands
        self._transport_controller = transport_controller
        self._validation_config = validation_config
        self._current_version_provider = current_version_provider

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateSession:
        await validate_prerequisites(
            commands=self._commands,
            tracker=self._tracker,
            config=self._validation_config,
            request=request,
        )
        transport_session = await self._transport_controller.prepare(request)
        return PreparedUpdateSession(
            request=request,
            current_version=self._current_version_provider(),
            transport_session=transport_session,
        )
