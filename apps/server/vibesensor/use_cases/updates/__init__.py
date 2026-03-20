"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle.  Update workflow orchestration is inlined in
  ``_run_update_inner()``.
- **Validation**: ``validation.py`` — runtime prerequisite checks for tools,
  privileges, rollback storage, and disk space before update orchestration.
- **Services**: ``manager.py`` — backend restart scheduling and runtime update
  lifecycle orchestration.
- **Operations**: ``installer.py`` (install/rollback), ``wifi.py`` (Wi-Fi
  connect/restore, diagnostics, network constants), ``releases.py``
  (GitHub release discovery), ``runner.py`` (process execution and
  command helpers).
- **State**: ``status.py`` (progress tracking, persistent state store,
  and runtime detail collection), ``models.py`` (data models).
"""
