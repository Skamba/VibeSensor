# [Non-security] UpdateManager is a god module and update job state is ephemeral, risking ambiguous restarts

**Labels:** reliability, maintainability, backend

## Summary

`UpdateManager` is a 1 080-line class in a 1 366-line file that handles WiFi
management, package installation, rollback, ESP firmware refresh, systemd
service restart, DNS probing, and runtime metadata collection. All update job
state (`UpdateJobStatus`) lives exclusively in memory. If the server restarts
mid-update (which the update process itself triggers via
`_schedule_service_restart()`), all state is lost and the next startup sees
an "idle" status with no record of the interrupted operation.

## Evidence

| File | Symbol / Line | Observation |
|---|---|---|
| `apps/server/vibesensor/update_manager.py` | `UpdateManager` class L286-1366 | 1 080 lines, single class |
| `update_manager.py` | `__init__()` L294-318 | State initialised in-memory: `self._status = UpdateJobStatus()`, `self._task = None` |
| `update_manager.py` | `UpdateJobStatus` L117-144 | Plain dataclass with no persistence; `log_tail`, `issues`, `state` all in RAM |
| `update_manager.py` | `start()` L326-352 | Creates `asyncio.Task` – reference stored only in `self._task` |
| `update_manager.py` | `_run_update()` L534-572 | Wraps entire update lifecycle; on crash, finally-block cleanup never runs |
| `update_manager.py` | `_schedule_service_restart()` L1200 | Intentionally restarts the service – guarantees loss of in-flight state |
| `update_manager.py` | `cancel()` L354-359 | Checks `self._task.done()` – after restart `_task` is None, always returns False |

### Restart scenario walkthrough

1. User starts update → `start()` sets `_status.state = running`, launches `_run_update` task
2. Update reaches `_schedule_service_restart()` (L1200) → systemd restarts the service
3. New process starts → `UpdateManager.__init__()` runs → `_status = UpdateJobStatus()` (idle)
4. UI polls `/api/settings/update/status` → sees `state: "idle"`
5. User (or automation) calls `start()` again → no guard against this, since `_task is None`
6. Two update cycles may overlap (old systemd restart + new update job)

### Responsibilities in one class

The class directly handles at least 8 distinct concerns:
- WiFi connection management (nmcli)
- DNS readiness probing
- Hotspot stop/restore
- Package download and installation (pip)
- Virtual environment management
- Filesystem rollback snapshots
- ESP firmware cache refresh
- Systemd service restart and environment configuration
- Runtime metadata collection

This makes the class difficult to test, understand, and modify safely.

## Impact

- After a service restart during an update, the UI shows "idle" and the user
  has no way to know whether the update succeeded or failed.
- A user may inadvertently trigger a second concurrent update after a restart.
- The monolithic class makes it hard to add features (e.g. progress persistence,
  partial retry) without risking regressions in unrelated functionality.
- Unit testing individual phases requires mocking the entire class.

## Suggested direction

- Persist `UpdateJobStatus` to disk (e.g. a JSON file or SQLite row) so that
  on restart the manager can detect an interrupted update and report its last
  known state.
- Add a startup check that reads persisted state and transitions from "running"
  to "interrupted" or "unknown" instead of defaulting to "idle".
- Extract distinct responsibilities into helper classes or modules (e.g.
  `WifiManager`, `PackageInstaller`, `RollbackManager`) that `UpdateManager`
  orchestrates.
