from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RuntimeHealthState:
    """Startup-readiness and managed-task failure state for operator health checks."""

    startup_state: str = "starting"
    startup_phase: str = "bootstrap"
    startup_error: str | None = None
    background_task_failures: dict[str, str] = field(default_factory=dict)
    startup_warnings: list[str] = field(default_factory=list)
    db_corruption_detected: bool = False
    db_corruption_details: str | None = None
    db_engine_unhealthy: bool = False
    db_engine_unhealthy_reason: str | None = None
    db_engine_unhealthy_details: str | None = None

    def set_phase(self, phase: str) -> None:
        self.startup_phase = phase
        if self.startup_state != "failed":
            self.startup_state = "starting"
            self.startup_error = None

    def mark_ready(self) -> None:
        self.startup_state = "ready"
        self.startup_phase = "ready"
        self.startup_error = None

    def mark_failed(self, phase: str, error: str) -> None:
        self.startup_state = "failed"
        self.startup_phase = phase
        self.startup_error = error

    def record_task_failure(self, task_name: str, error: str) -> None:
        self.background_task_failures[task_name] = error

    def clear_task_failure(self, task_name: str) -> None:
        self.background_task_failures.pop(task_name, None)

    def mark_db_corrupted(self, details: str) -> None:
        self.db_corruption_detected = True
        self.db_corruption_details = details

    def mark_db_engine_unhealthy(self, reason: str, details: str) -> None:
        self.db_engine_unhealthy = True
        self.db_engine_unhealthy_reason = reason
        self.db_engine_unhealthy_details = details
