"""Live diagnostics package — real-time severity tracking and event emission.

Backward-compatible re-exports: all symbols that were public in the old
single-file ``live_diagnostics.py`` module are available at package level.
"""

from ._types import (  # noqa: F401
    SEVERITY_KEYS,
    SOURCE_KEYS,
    _combine_amplitude_strength_db,
    _MatrixCountEvent,
    _MatrixSecondsEvent,
    _RecentEvent,
    _TrackerLevelState,
)
from .engine import LiveDiagnosticsEngine  # noqa: F401
from .severity_matrix import _copy_matrix, _new_matrix  # noqa: F401
