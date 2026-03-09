"""Updater subsystem package.

``manager.py`` remains the public entry point (facade), while focused
modules own each concern:

Module topology
---------------
- **Facade**: ``manager.py`` — public ``UpdateManager`` API for routes and
  runtime lifecycle.
- **Workflow**: ``workflow.py`` — high-level multi-phase update orchestration.
- **Operations**: ``installer.py`` (install/rollback), ``wifi.py`` (Wi-Fi
  connect/restore), ``releases.py`` (GitHub release discovery), ``commands.py``
  (shell command helpers), ``runner.py`` (process execution), ``service_control.py``
  (systemd management).
- **State**: ``status.py`` (progress tracking), ``state_store.py`` (persistent
  state), ``models.py`` (data models).
- **Validation**: ``validation.py`` (prerequisite checks).
- **Diagnostics**: ``runtime_details.py`` (hash/version inspection), ``network.py``
  (DNS / connectivity).

Composition rule: the ``UpdateManager`` constructor wires these modules via
keyword-only arguments and config, then delegates all public operations to
the ``UpdateWorkflow`` or individual service objects.
"""
