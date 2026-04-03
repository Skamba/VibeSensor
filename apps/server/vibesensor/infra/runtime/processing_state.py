"""Observable processing-loop state exposed to health reporting and runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ProcessingHealth(StrEnum):
    """Health status of the processing loop."""

    OK = "ok"
    DEGRADED = "degraded"
    FATAL = "fatal"


@dataclass(slots=True)
class ProcessingLoopState:
    """Mutable health and timing state for the runtime processing loop."""

    processing_state: ProcessingHealth = ProcessingHealth.OK
    processing_failure_count: int = 0
    processing_failure_categories: dict[str, int] = field(default_factory=dict)
    last_failure_category: str | None = None
    last_failure_message: str | None = None
    sample_rate_mismatch_logged: set[str] = field(default_factory=set)
    frame_size_mismatch_logged: set[str] = field(default_factory=set)
    last_tick_duration_s: float = 0.0
    max_tick_duration_s: float = 0.0
    tick_count: int = 0
