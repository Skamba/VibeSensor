"""Backward-compatibility wrapper for the update subsystem.

The implementation now lives in the ``vibesensor.update`` package.
This module re-exports all public symbols so that existing imports
(``from vibesensor.update_manager import UpdateManager``, etc.)
continue to work without changes.
"""

from __future__ import annotations

from .update.manager import (  # noqa: F401
    DEFAULT_GIT_BRANCH,
    DEFAULT_GIT_REMOTE,
    DEFAULT_REBUILD_PATH,
    DEFAULT_ROLLBACK_DIR,
    DOWNLOAD_TIMEOUT_S,
    ESP_FIRMWARE_REFRESH_TIMEOUT_S,
    GIT_OP_TIMEOUT_S,
    REBUILD_OP_TIMEOUT_S,
    REBUILD_RETRY_DELAY_S,
    REINSTALL_OP_TIMEOUT_S,
    SERVICE_CONTRACTS_DIR,
    SERVICE_ENV_DROPIN,
    TRANSIENT_REBUILD_ERROR_MARKERS,
    UI_BUILD_METADATA_FILE,
    UPDATE_RESTART_UNIT,
    UPDATE_SERVICE_NAME,
    UPDATE_TIMEOUT_S,
    UpdateManager,
)
from .update.models import UpdateIssue, UpdateJobStatus, UpdatePhase, UpdateState  # noqa: F401
from .update.network import (  # noqa: F401
    DNS_PROBE_HOST,
    DNS_READY_MIN_WAIT_S,
    DNS_RETRY_INTERVAL_S,
    HOTSPOT_RESTORE_DELAY_S,
    HOTSPOT_RESTORE_RETRIES,
    NMCLI_TIMEOUT_S,
    UPLINK_CONNECT_WAIT_S,
    UPLINK_CONNECTION_NAME,
    UPLINK_FALLBACK_DNS,
    parse_wifi_diagnostics,
)
from .update.runner import CommandRunner  # noqa: F401
from .update.runner import sanitize_log_line as _sanitize_log_line  # noqa: F401
from .update.state_store import UpdateStateStore  # noqa: F401

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
