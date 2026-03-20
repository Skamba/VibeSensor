"""Run-history persistence port used by history and recording use-cases.

This protocol captures the `HistoryDB` surface currently consumed by
`use_cases/history/` and `use_cases/run/`. Issue `#814` will later consolidate
these focused protocols into a shared `ports.py` module.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from vibesensor.shared.types.json_types import JsonObject

__all__ = ["RunPersistence"]


class RunPersistence(Protocol):
    """Persistence operations needed by history queries and recording flows."""

    def list_runs(self, limit: int = 500) -> list[JsonObject]: ...

    def get_run(self, run_id: str) -> JsonObject | None: ...

    def get_run_metadata(self, run_id: str) -> JsonObject | None: ...

    def iter_run_samples(
        self,
        run_id: str,
        batch_size: int = 1000,
    ) -> Iterator[list[JsonObject]]: ...

    def delete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]: ...

    def create_run(
        self,
        run_id: str,
        start_time_utc: str,
        metadata: JsonObject,
    ) -> None: ...

    def append_samples(self, run_id: str, samples: list[JsonObject]) -> None: ...

    def finalize_run(
        self,
        run_id: str,
        end_time_utc: str,
        metadata: JsonObject | None = None,
    ) -> bool: ...

    def store_analysis(self, run_id: str, analysis: JsonObject) -> bool: ...

    def store_analysis_error(self, run_id: str, error: str) -> bool: ...

    def analyzing_run_health(self) -> JsonObject: ...
