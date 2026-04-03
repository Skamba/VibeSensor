"""Updater subsystem package.

The updater now has one explicit execution boundary per concern:

- ``manager.py`` exposes the public API only.
- ``runtime.py`` composes the concrete collaborators used by that facade.
- ``coordinator.py`` owns validation, transport preparation, release work, and success finalization.
- ``transport_sessions.py`` defines the transport-session interface used by
  lifecycle, recovery, and execution.
- ``usb_status.py`` inspects Linux/NetworkManager state for USB internet readiness.
- ``usb_transport.py`` owns USB transport execution behavior.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, and secret redaction.
"""
