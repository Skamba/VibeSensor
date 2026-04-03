"""Updater subsystem package.

The updater now has one explicit execution boundary per concern:

- ``manager.py`` exposes the public API only.
- ``runtime.py`` composes the concrete collaborators used by that facade.
- ``preparation.py`` owns validation, transport preparation, and version
  resolution for one run.
- ``coordinator.py`` owns only release planning/execution sequencing.
- ``release_planner.py`` interprets discovered release state into one execution plan.
- ``transport_lifecycle.py`` owns transport preparation, success completion,
  cleanup, and interrupted-run recovery.
- ``workflow_executor.py`` owns plan execution while ``success_finalizer.py`` owns
  success/restart finalization.
- ``transport_sessions.py`` defines the transport-session interface used by
  the transport lifecycle boundary.
- ``usb_status.py`` inspects Linux/NetworkManager state for USB internet readiness.
- ``usb_transport.py`` owns USB transport execution behavior.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, and secret redaction.
"""
