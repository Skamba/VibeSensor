"""Canonical request-scoped update workflow orchestration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from vibesensor.use_cases.updates.finalization import UpdateWorkflowFinalizer
from vibesensor.use_cases.updates.models import UpdateRequest
from vibesensor.use_cases.updates.preparation import UpdatePreparationCoordinator
from vibesensor.use_cases.updates.release_planner import UpdateReleasePlanner
from vibesensor.use_cases.updates.run_models import PreparedUpdateRun
from vibesensor.use_cases.updates.workflow_executor import UpdateWorkflowExecutor

__all__ = ["UpdateWorkflow"]


@dataclass(frozen=True, slots=True)
class UpdateWorkflow:
    """Run one update request through the canonical workflow lifecycle."""

    preparation: UpdatePreparationCoordinator
    release_planner: UpdateReleasePlanner
    workflow_executor: UpdateWorkflowExecutor
    finalizer: UpdateWorkflowFinalizer

    async def run(
        self,
        *,
        request: UpdateRequest,
    ) -> None:
        prepared: PreparedUpdateRun | None = None
        prior_error: BaseException | None = None
        try:
            prepared = await self.preparation.prepare(request)
            planned = await self.release_planner.plan(prepared)
            await self.workflow_executor.execute(planned)
        except asyncio.CancelledError as exc:
            prior_error = exc
            raise
        except Exception as exc:
            prior_error = exc
            raise
        finally:
            await self.finalizer.finalize(
                None if prepared is None else prepared.prepared_transport,
                prior_error=prior_error,
            )
