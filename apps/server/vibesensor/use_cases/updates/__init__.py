"""Updater subsystem package.

The updater now has one explicit run-scoped workflow boundary per concern:

- ``manager.py`` exposes the public API only.
- ``runtime.py`` composes one canonical runtime graph with shared transport
  sessions, status tracking, and workflow collaborators.
- ``workflow.py`` owns request-scoped orchestration across preparation,
  planning, and execution.
- ``preparation.py`` owns validation, transport preparation, and current-version
  observation for one run while returning the resolved transport session
  explicitly.
- ``release_planner.py`` interprets discovered release state into one canonical
  execution plan tied to that prepared session.
- ``workflow_executor.py`` owns plan execution while ``success_finalizer.py`` owns
  success/restart finalization against the explicit session.
- ``transport_sessions.py`` defines the transport-session interface and request/
  status-based resolution boundary.
- ``usb_status.py`` inspects Linux/NetworkManager state for USB internet readiness.
- ``usb_transport.py`` owns USB transport execution behavior.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, and secret redaction.
"""
