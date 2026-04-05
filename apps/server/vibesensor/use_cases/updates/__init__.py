"""Updater subsystem package.

The updater now has one explicit run-scoped workflow boundary per concern:

- ``manager.py`` owns the public update-job runtime lifecycle: start, cancel,
  task supervision, timeout handling, and startup recovery.
- ``runtime.py`` is the public updater-runtime facade that returns one canonical
  manager instance.
- ``runtime_config.py`` owns runtime config resolution.
- ``runtime_core.py`` owns status-tracker and command-executor assembly.
- ``workflow_runtime.py`` owns workflow assembly from the focused planning,
  release execution, transport, and core collaborators.
- ``run_models.py`` holds the canonical prepared/planned run models shared
  across the workflow.
- ``workflow.py`` owns request-scoped orchestration across preparation,
  planning, execution, and explicit post-run finalization handoff.
- ``preparation.py`` owns validation and transport preparation for one run.
- ``release_planner.py`` owns current-version observation and release selection.
- ``server_release_execution.py`` owns the staged server-release install path.
- ``workflow_executor.py`` owns plan dispatch and success completion.
- ``completion.py`` owns post-success transport completion and restart follow-up.
- ``finalization.py`` owns unconditional transport cleanup and runtime refresh.
- ``privilege.py`` owns sudo/privilege-escalation helpers used by command
  execution and transport modules.
- ``runner.py`` owns command execution primitives (``CommandRunner``,
  ``UpdateCommandExecutor``), command reporting, and log-line sanitisation.
- ``transport/`` owns prepared-transport interfaces, transport coordination,
  transport-neutral uplink readiness, and USB transport execution behavior.
- ``usb_status.py`` owns the USB internet readiness service facade, while
  ``usb_status_inspection.py`` and ``usb_status_evaluation.py`` split raw
  Linux/NM probing from readiness ranking and diagnostics.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, secret
  redaction, and the explicit tracker used by manager/runtime composition.
"""
