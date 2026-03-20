"""Signal-processing port used by recording use-cases.

This protocol captures the narrow ``SignalProcessor`` surface currently
consumed by ``use_cases/run/``. Issue ``#814`` will later consolidate these
focused protocols into a shared ``ports.py`` module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

__all__ = ["SignalSource"]


class SignalSource(Protocol):
    """Latest-sample and metrics access needed by recording flows."""

    def clients_with_recent_data(
        self,
        client_ids: list[str],
        max_age_s: float = 3.0,
    ) -> list[str]: ...

    def latest_metrics(self, client_id: str) -> Mapping[str, object]: ...

    def latest_sample_xyz(self, client_id: str) -> tuple[float, float, float] | None: ...

    def latest_sample_rate_hz(self, client_id: str) -> int | None: ...
