"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle. Delegates update sequencing to ``workflow.py``.
- **Workflow**: ``workflow.py`` — ``UpdateWorkflow`` runs the full update
  sequence over validation, transport preparation, and release application.
- **Transport sessions**: ``transport_sessions.py`` — canonical Wi-Fi and USB
  transport-session boundary used by workflow, cleanup, and startup recovery.
- **Release application**: ``release_application.py`` — release discovery,
  download, install, firmware refresh, and restart scheduling after transport
  preparation succeeds.
- **Recovery**: ``recovery.py`` — ``InterruptedUpdateRecovery`` collaborator
  for interrupted-job detection, cleanup, and persistence on startup.
- **Validation**: ``validation.py`` — runtime prerequisite checks for tools,
  privileges, rollback storage, and disk space before update orchestration.
- **Services**: ``job_executor.py`` — task ownership, cancellation,
  timeout handling, and cleanup coordination for long-running update jobs.
- **Firmware**: ``firmware/`` — ESP flash orchestration, firmware cache,
  bundle validation, refresh, release fetcher, and flash-specific contracts.
- **Wi-Fi**: ``wifi/`` — uplink setup, readiness policy, hotspot recovery,
  diagnostics parsing, and the thin Wi-Fi workflow coordinator.
- **Releases**: ``releases/`` — GitHub release discovery, validation, and
  updater-facing download helpers.
- **Operations**: ``installer.py`` (install policy facade),
  ``wheel_installation.py`` (wheel install + verification execution),
  ``rollback_snapshot_builder.py`` (rollback snapshot capture),
  ``rollback_executor.py`` (rollback candidate selection + execution),
  ``artifact_validation.py`` (wheel validation + checksums),
  ``rollback_snapshot.py`` (rollback metadata + stored wheels),
  ``runner.py`` (process execution and command helpers), and
  ``venv_paths.py`` (reinstall venv discovery).
- **State**: ``status.py`` (progress tracking, persistent state store,
  and runtime detail collection), ``models.py`` (data models and
  ``validate_update_request()`` request-shape validation).
"""
