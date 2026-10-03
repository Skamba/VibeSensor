"""Updater subsystem package.

- ``manager.py`` owns the public updater API: start, cancel, task supervision,
  timeout/cancellation reporting, and startup recovery entry.
- ``job.py`` owns one update run as a linear async flow (validate, prepare
  transport, check release, refresh firmware or stage and install into a new
  venv slot, complete, switch, restart, clean up) plus recovery of
  interrupted runs and reporting of boot-check reverts.
- ``runtime.py`` composes the manager, job, and their collaborators.
- ``venv_slots.py`` owns the A/B venv layout under ``.venv`` (adoption of a
  plain venv, clone, activate, prune); ``venv_install.py`` installs a release
  into a new slot and smoke-tests it; ``boot_check.py`` is the stdlib-only
  launcher that confirms or reverts a new slot after the restart.
- ``release_staging.py`` owns release wheel download and SHA-256 verification.
- ``artifact_validation.py`` owns wheel artifact and metadata validation.
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
