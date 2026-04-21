"""Explicit shutdown phase runner for the runtime lifecycle."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiosqlite
import anyio

if TYPE_CHECKING:
    from vibesensor.infra.runtime.background_task_coordinator import BackgroundTaskCoordinator
    from vibesensor.infra.runtime.lifecycle import LifecycleRuntime
    from vibesensor.infra.runtime.udp_transport_lifecycle import UdpTransportLifecycle


@dataclass(frozen=True, slots=True)
class LifecycleShutdownIssue:
    """One categorized shutdown failure captured during lifecycle stop."""

    phase: str
    message: str
    exception: Exception


@dataclass(frozen=True, slots=True)
class LifecycleShutdownResult:
    """Collected shutdown issues plus managed jobs that outlived cancellation."""

    lingering_background: tuple[str, ...]
    lingering_managed: tuple[asyncio.Task[None], ...]
    issues: tuple[LifecycleShutdownIssue, ...]


class LifecycleShutdownSequence:
    """Run the lifecycle shutdown phases while collecting typed failures."""

    __slots__ = ("_background_tasks", "_logger", "_runtime", "_udp_transport_lifecycle")

    def __init__(
        self,
        *,
        runtime: LifecycleRuntime,
        background_tasks: BackgroundTaskCoordinator,
        udp_transport_lifecycle: UdpTransportLifecycle,
        logger: logging.Logger,
    ) -> None:
        self._runtime = runtime
        self._background_tasks = background_tasks
        self._udp_transport_lifecycle = udp_transport_lifecycle
        self._logger = logger

    async def run(self) -> LifecycleShutdownResult:
        issues: list[LifecycleShutdownIssue] = []
        self._stop_ingress(issues)
        await self._udp_transport_lifecycle.shutdown()
        lingering_background = await self._background_tasks.cancel_all(timeout_s=15.0)
        lingering_managed = await self._cancel_managed_jobs()
        await self._drain_analysis()
        await self._shutdown_worker_pool(issues)
        await self._close_history_db(issues)
        if not lingering_background:
            await self._background_tasks.close()
        return LifecycleShutdownResult(
            lingering_background=tuple(lingering_background),
            lingering_managed=tuple(lingering_managed),
            issues=tuple(issues),
        )

    def _stop_ingress(self, issues: list[LifecycleShutdownIssue]) -> None:
        try:
            self._runtime.control_plane.close()
        except OSError as exc:
            issues.append(
                LifecycleShutdownIssue(
                    phase="stop_ingress",
                    message="Error closing control plane",
                    exception=exc,
                )
            )

    async def _cancel_managed_jobs(self) -> list[asyncio.Task[None]]:
        from vibesensor.infra.runtime.managed_job_shutdown import ManagedJobShutdown

        managed_shutdown = ManagedJobShutdown(
            [
                self._runtime.update_manager,
                self._runtime.esp_flash_manager,
            ]
        )
        return await managed_shutdown.cancel(timeout_s=10.0)

    async def _drain_analysis(self) -> None:
        analysis_timeout_s = self._runtime.shutdown_analysis_timeout_s
        shutdown_report = await anyio.to_thread.run_sync(
            self._runtime.run_recorder.shutdown_report,
            analysis_timeout_s,
        )
        if not shutdown_report.completed:
            self._logger.warning(
                "Post-analysis did not finish within %.1fs on shutdown; "
                "results for the last run may be lost. active_run_before_stop=%s "
                "queue_depth=%d active_run=%s oldest_queue_age_s=%s write_error=%s",
                analysis_timeout_s,
                shutdown_report.active_run_id_before_stop,
                shutdown_report.analysis_queue_depth,
                shutdown_report.analysis_active_run_id,
                shutdown_report.analysis_queue_oldest_age_s,
                shutdown_report.write_error,
            )

    async def _shutdown_worker_pool(self, issues: list[LifecycleShutdownIssue]) -> None:
        try:
            await anyio.to_thread.run_sync(self._runtime.worker_pool.shutdown, True)
        except (OSError, RuntimeError) as exc:
            issues.append(
                LifecycleShutdownIssue(
                    phase="shutdown_worker_pool",
                    message="Error shutting down worker pool",
                    exception=exc,
                )
            )

    async def _close_history_db(self, issues: list[LifecycleShutdownIssue]) -> None:
        try:
            await self._runtime.history_db.aclose()
        except (aiosqlite.Error, OSError) as exc:
            issues.append(
                LifecycleShutdownIssue(
                    phase="close_history_db",
                    message="Error closing history DB",
                    exception=exc,
                )
            )
