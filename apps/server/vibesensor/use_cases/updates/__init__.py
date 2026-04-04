"""Updater subsystem package.

The updater now has one explicit run-scoped workflow boundary per concern:

- ``manager.py`` exposes the public API only.
- ``runtime.py`` composes one canonical runtime graph with explicit status
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
- ``workflow_executor.py`` owns plan execution while ``completion.py`` owns
  success/restart finalization against the explicit prepared transport.
- ``cleanup.py`` owns transport cleanup only, while ``runtime_refresh.py``
  refreshes runtime/build metadata after workflow exit.
- ``transport_sessions.py`` defines the transport-session interface and request/
  status-based resolution boundary.
- ``transport_coordinator.py`` owns prepare/cleanup/recovery/success transport
  lifecycle sequencing against those transport sessions.
- ``usb_status.py`` inspects Linux/NetworkManager state for USB internet readiness.
- ``usb_transport.py`` owns USB transport execution behavior.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, secret
  redaction, and the explicit service bundle used by runtime composition.
"""
