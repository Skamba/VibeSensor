"""Preparation boundary for one update workflow run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vibesensor.use_cases.updates.models import UpdateRequest, UpdateValidationConfig
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusController, UpdateStatusRecorder
from vibesensor.use_cases.updates.transport_coordinator import (
    PreparedUpdateTransport,
    UpdateTransportCoordinator,
)
from vibesensor.use_cases.updates.validation import validate_prerequisites

__all__ = [
    "CurrentVersionProvider",
    "PreparedUpdateWorkflow",
    "UpdatePreparationCoordinator",
]

CurrentVersionProvider = Callable[[], str]


@dataclass(frozen=True, slots=True)
class PreparedUpdateWorkflow:
    """Validated update workflow state with one prepared transport lifecycle."""

    current_version: str
    transport: PreparedUpdateTransport


class UpdatePreparationCoordinator:
    """Own validation, transport setup, and version resolution before release work."""

    __slots__ = (
        "_commands",
        "_current_version_provider",
        "_status_controller",
        "_status_recorder",
        "_transport_coordinator",
        "_validation_config",
    )

    def __init__(
        self,
        *,
        status_controller: UpdateStatusController,
        status_recorder: UpdateStatusRecorder,
        commands: UpdateCommandExecutor,
        transport_coordinator: UpdateTransportCoordinator,
        validation_config: UpdateValidationConfig,
        current_version_provider: CurrentVersionProvider,
    ) -> None:
        self._status_controller = status_controller
        self._status_recorder = status_recorder
        self._commands = commands
        self._transport_coordinator = transport_coordinator
        self._validation_config = validation_config
        self._current_version_provider = current_version_provider

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateWorkflow:
        await validate_prerequisites(
            commands=self._commands,
            controller=self._status_controller,
            recorder=self._status_recorder,
            config=self._validation_config,
            request=request,
        )
        return PreparedUpdateWorkflow(
            current_version=self._current_version_provider(),
            transport=await self._transport_coordinator.prepare(request),
        )
