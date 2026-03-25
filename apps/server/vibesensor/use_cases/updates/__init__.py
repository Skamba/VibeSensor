"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle. Update workflow orchestration is inlined in
  ``_run_update_inner()``.
- **Validation**: ``validation.py`` — runtime prerequisite checks for tools,
  privileges, rollback storage, and disk space before update orchestration.
- **Services**: ``manager.py`` — backend restart scheduling and runtime update
  workflow orchestration; ``job_executor.py`` — task ownership, cancellation,
  timeout handling, and cleanup coordination for long-running update jobs.
- **Firmware**: ``firmware/`` — ESP flash orchestration, firmware cache,
  bundle validation, refresh, release fetcher, and flash-specific contracts.
- **Wi-Fi**: ``wifi/`` — uplink setup, readiness policy, hotspot recovery,
  diagnostics parsing, and the thin Wi-Fi workflow coordinator.
- **Releases**: ``releases/`` — GitHub release discovery, validation, and
  updater-facing download helpers.
- **Operations**: ``installer.py`` (install/rollback orchestration),
  ``artifact_validation.py`` (wheel validation + checksums),
  ``rollback_snapshot.py`` (rollback metadata + stored wheels),
  ``runner.py`` (process execution and command helpers), and
  ``venv_paths.py`` (reinstall venv discovery).
- **State**: ``status.py`` (progress tracking, persistent state store,
  and runtime detail collection), ``models.py`` (data models).
"""
