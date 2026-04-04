"""Updater subsystem package.

The updater now has one explicit run-scoped workflow boundary per concern:

- ``manager.py`` owns the public update-job runtime lifecycle: start, cancel,
  task supervision, timeout handling, and startup recovery.
- ``runtime.py`` composes one canonical manager instance with explicit status
  services, transport lifecycle coordination, and workflow collaborators.
- ``run_models.py`` holds the canonical prepared/planned run models shared
  across the workflow.
- ``workflow.py`` owns request-scoped orchestration across preparation,
  planning, execution, and explicit post-run finalization.
- ``preparation.py`` owns validation, transport preparation, and current-version
  observation for one run while returning the prepared transport lifecycle
  explicitly.
- ``release_planner.py`` interprets discovered release state into one canonical
  execution plan tied to that prepared session.
- ``workflow_executor.py`` owns plan execution plus success/restart finalization
  against the explicit prepared transport handle.
- ``runtime_refresh.py`` refreshes runtime/build metadata after workflow exit.
- ``transport_lifecycles.py`` defines the prepared-transport and lifecycle
  interfaces plus request/status-based transport resolution.
- ``transport_coordinator.py`` owns lifecycle selection, prepare-time rollback,
  cleanup error wrapping, and interrupted-run recovery.
- ``usb_status.py`` inspects Linux/NetworkManager state for USB internet readiness.
- ``usb_transport.py`` owns USB transport execution behavior.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, secret
  redaction, and the explicit service bundle used by manager/runtime composition.
"""
