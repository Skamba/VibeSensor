"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle.
- **Workflow**: ``workflow.py`` — orchestration, service control, and
  prerequisite validation.
- **Operations**: ``installer.py`` (install/rollback), ``wifi.py`` (Wi-Fi
  connect/restore, diagnostics, network constants), ``releases.py``
  (GitHub release discovery), ``runner.py`` (process execution and
  command helpers).
- **State**: ``status.py`` (progress tracking, persistent state store,
  and runtime detail collection), ``models.py`` (data models).

Composition rule: the ``UpdateManager`` constructor wires these modules via
keyword-only arguments and config, then delegates all public operations to
the ``UpdateWorkflow`` or individual service objects.
"""
