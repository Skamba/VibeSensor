"""Preparation boundary for one update workflow run."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.use_cases.updates.models import UpdateRequest, UpdateValidationConfig
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStatusTracker
from vibesensor.use_cases.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.use_cases.updates.validation import validate_prerequisites

__all__ = ["CurrentVersionProvider", "UpdatePreparationCoordinator"]

CurrentVersionProvider = Callable[[], str]


class UpdatePreparationCoordinator:
    """Own validation, transport setup, and version resolution before release work."""

    __slots__ = (
        "_commands",
        "_current_version_provider",
        "_status",
        "_transport_coordinator",
        "_validation_config",
    )

    def __init__(
        self,
        *,
        status: UpdateStatusTracker,
        commands: UpdateCommandExecutor,
        transport_coordinator: UpdateTransportCoordinator,
        validation_config: UpdateValidationConfig,
        current_version_provider: CurrentVersionProvider,
    ) -> None:
        self._status = status
        self._commands = commands
        self._transport_coordinator = transport_coordinator
        self._validation_config = validation_config
        self._current_version_provider = current_version_provider

    async def prepare(self, request: UpdateRequest) -> PreparedUpdateRun:
        await validate_prerequisites(
            commands=self._commands,
            status=self._status,
            config=self._validation_config,
            request=request,
        )
        return PreparedUpdateRun(
            current_version=self._current_version_provider(),
            prepared_transport=await self._transport_coordinator.prepare(request),
        )
