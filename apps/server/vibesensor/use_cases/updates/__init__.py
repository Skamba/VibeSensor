"""Updater subsystem package.

- ``manager.py`` owns the public updater API: start, cancel, task supervision,
  timeout/cancellation reporting, and startup recovery entry.
- ``job.py`` owns one update run as a linear async flow (validate, prepare
  transport, check release, refresh firmware or stage/snapshot/install with
  rollback, complete, clean up) plus recovery of interrupted runs.
- ``runtime.py`` composes the manager, job, and their collaborators.
- ``rollback.py`` owns rollback snapshot capture, restore, and verification.
- ``release_staging.py`` owns release wheel download and SHA-256 verification.
- ``wheel_installation.py`` / ``artifact_validation.py`` own wheel install and
  artifact validation.
- ``validation.py`` owns pre-flight prerequisite checks.
- ``privilege.py`` owns sudo/privilege-escalation helpers used by command
  execution and transport modules.
- ``runner.py`` owns command execution primitives (``CommandRunner``,
  ``UpdateCommandExecutor``), command reporting, and log-line sanitisation.
- ``transport/`` owns prepared-transport interfaces, transport coordination,
  transport-neutral uplink readiness, and USB transport execution behavior.
- ``usb_status.py`` owns the USB internet readiness service, while
  ``usb_status_inspection.py`` and ``usb_status_evaluation.py`` split raw
  Linux/NM probing from readiness ranking and diagnostics.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``firmware/`` owns ESP firmware cache refresh and flashing.
- ``status/`` owns the status tracker (phase rules, log/issues, secrets,
  terminal outcomes) plus the persisted/HTTP payload codec and state store.
"""
