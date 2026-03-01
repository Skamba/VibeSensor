"""Backward-compatibility wrapper for the update subsystem.

The implementation now lives in the ``vibesensor.update`` package.
This module re-exports all public symbols so that existing imports
(``from vibesensor.update_manager import UpdateManager``, etc.)
continue to work without changes.
"""

from __future__ import annotations

from .update.manager import (
    UpdateManager,
)
from .update.models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState
from .update.network import (
    parse_wifi_diagnostics,
)
from .update.runner import CommandRunner
from .update.runner import sanitize_log_line as _sanitize_log_line
from .update.state_store import UpdateStateStore

__all__ = [
    "CommandRunner",
    "UpdateIssue",
    "UpdateJobStatus",
    "UpdateManager",
    "UpdatePhase",
    "UpdateState",
    "UpdateStateStore",
    "_sanitize_log_line",
    "parse_wifi_diagnostics",
]
