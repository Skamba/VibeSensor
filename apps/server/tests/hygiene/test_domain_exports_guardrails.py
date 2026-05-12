"""High-signal guardrails for the public domain facade."""

from __future__ import annotations


def test_public_domain_facade_supports_representative_behavior() -> None:
    """Catch accidental removal of the supported ``vibesensor.domain`` import facade."""
    from vibesensor.domain import (
        Finding,
        Run,
        RunCapture,
        RunStatus,
        SuitabilityCheck,
        speed_bin_label,
        transition_run,
    )

    run = Run(run_id="facade-run")
    run.start()

    assert run.is_recording is True
    assert RunCapture(run_id="facade-run").run_id == "facade-run"
    assert Finding(finding_id="F001").finding_id == "F001"
    assert SuitabilityCheck("SUITABILITY_CHECK_SPEED_VARIATION", "pass").passed is True
    assert transition_run(None, RunStatus.RECORDING) is RunStatus.RECORDING
    assert speed_bin_label(83.0) == "80-90 km/h"
