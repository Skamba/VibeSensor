"""Updater subsystem package.

The updater now has one explicit run-scoped workflow boundary per concern:

- ``manager.py`` owns the public update-job runtime lifecycle: start, cancel,
  task supervision, timeout handling, and startup recovery.
- ``runtime.py`` is the public updater-runtime facade that returns one canonical
  manager instance.
- ``runtime_config.py`` owns runtime config resolution.
- ``runtime_core.py`` owns status-tracker and command-executor assembly.
- ``release_planning_runtime.py`` owns release-planner assembly.
- ``release_execution_runtime.py`` owns release-execution assembly.
- ``workflow_runtime.py`` owns workflow assembly from the focused planning,
  execution, transport, and core collaborators.
- ``run_models.py`` holds the canonical prepared/planned run models shared
  across the workflow.
- ``workflow.py`` owns request-scoped orchestration across preparation,
  planning, execution, and explicit post-run finalization handoff.
- ``preparation.py`` owns validation, transport preparation, and current-version
  observation for one run while returning the prepared transport lifecycle
  explicitly.
- ``release_planner.py`` interprets discovered release state into one canonical
  execution plan tied to that prepared session.
- ``workflow_executor.py`` owns plan execution only.
- ``completion.py`` owns post-success transport completion and restart follow-up.
- ``finalization.py`` owns unconditional transport cleanup and runtime refresh.
- ``transport/`` owns prepared-transport interfaces, transport coordination,
  transport-neutral uplink readiness, and USB transport execution behavior.
- ``usb_status.py`` owns the USB internet readiness service facade, while
  ``usb_status_inspection.py`` and ``usb_status_evaluation.py`` split raw
  Linux/NM probing from readiness ranking and diagnostics.
- ``wifi/`` owns Wi-Fi-specific transport execution.
- ``status/`` owns state transitions, persistence, logging buffers, secret
  redaction, and the explicit tracker used by manager/runtime composition.
"""
