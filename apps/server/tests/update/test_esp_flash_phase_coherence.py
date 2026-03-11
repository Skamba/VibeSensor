"""Regression tests for EspFlashManager._finalize phase coherence — Diego3 fixes.

Prior to the fix, _finalize() only updated `state` but left `phase` at whatever
it was during the running job (e.g. "erasing").  This produced incoherent status
payloads like  state="cancelled" + phase="erasing"  that confused API consumers.

The fix aligns `phase` with terminal states:
  - EspFlashState.cancelled  → phase = "cancelled"
  - EspFlashState.failed     → phase = "failed"
  - EspFlashState.success    → phase unchanged (caller sets "done" just before)

These tests verify the phase is always coherent after _finalize().
"""

from __future__ import annotations

from pathlib import Path

from vibesensor.update.esp_flash_manager import (
    EspFlashManager,
    EspFlashState,
    EspFlashStatus,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_manager(tmp_path: Path) -> EspFlashManager:
    """Return an EspFlashManager with minimal construction."""
    return EspFlashManager()


def _manager_with_active_phase(phase: str) -> EspFlashManager:
    """Return a manager whose status has been set to a mid-run phase."""
    mgr = EspFlashManager()
    mgr._status = EspFlashStatus(
        state=EspFlashState.running,
        phase=phase,
    )
    return mgr


# ── _finalize phase coherence ─────────────────────────────────────────────────


def test_finalize_cancelled_sets_phase_cancelled() -> None:
    """After _finalize(cancelled), phase must be 'cancelled', not a stale running phase."""
    mgr = _manager_with_active_phase("erasing")
    mgr._finalize(state=EspFlashState.cancelled, error="cancelled by user")

    assert mgr._status.state == EspFlashState.cancelled
    assert mgr._status.phase == "cancelled", (
        f"Expected phase='cancelled' after cancelled finalization, got {mgr._status.phase!r}"
    )


def test_finalize_failed_sets_phase_failed() -> None:
    """After _finalize(failed), phase must be 'failed', not a stale running phase."""
    mgr = _manager_with_active_phase("flashing")
    mgr._finalize(state=EspFlashState.failed, error="esptool returned non-zero")

    assert mgr._status.state == EspFlashState.failed
    assert mgr._status.phase == "failed", (
        f"Expected phase='failed' after failed finalization, got {mgr._status.phase!r}"
    )


def test_finalize_success_does_not_override_done_phase() -> None:
    """After _finalize(success), phase should remain as the caller set it ('done').

    The success path sets phase='done' *before* calling _finalize().  The
    _finalize() method must NOT overwrite that with anything else.
    """
    mgr = _manager_with_active_phase("done")  # caller set this just before _finalize
    mgr._finalize(state=EspFlashState.success)

    assert mgr._status.state == EspFlashState.success
    assert mgr._status.phase == "done", (
        f"Expected phase='done' for success, got {mgr._status.phase!r}"
    )


def test_finalize_cancelled_error_message_stored() -> None:
    """The error string passed to _finalize(cancelled) is preserved on status."""
    mgr = _manager_with_active_phase("preparing")
    mgr._finalize(state=EspFlashState.cancelled, error="user pressed cancel")

    assert mgr._status.error == "user pressed cancel"


def test_finalize_failed_error_message_stored() -> None:
    """The error string passed to _finalize(failed) is accessible on status."""
    mgr = _manager_with_active_phase("erasing")
    mgr._finalize(state=EspFlashState.failed, error="serial port disconnected")

    assert mgr._status.error == "serial port disconnected"


def test_finalize_adds_history_entry() -> None:
    """Every _finalize call appends an entry to the internal history list."""
    mgr = _manager_with_active_phase("erasing")
    assert len(mgr._history) == 0

    mgr._finalize(state=EspFlashState.failed, error="test failure")

    assert len(mgr._history) == 1
    entry = mgr._history[0]
    assert entry.state == EspFlashState.failed
    assert entry.error == "test failure"


def test_finalize_cancelled_history_entry_has_coherent_state() -> None:
    """History entry state must match the terminal state passed to _finalize."""
    mgr = _manager_with_active_phase("flashing")
    mgr._finalize(state=EspFlashState.cancelled, error="cancelled")

    entry = mgr._history[0]
    assert entry.state == EspFlashState.cancelled


def test_finalize_success_sets_last_success_at() -> None:
    """On success, last_success_at must be populated with finished_at value."""
    mgr = _manager_with_active_phase("done")
    mgr._finalize(state=EspFlashState.success)

    assert mgr._status.last_success_at is not None
    assert mgr._status.last_success_at == mgr._status.finished_at


def test_finalize_non_success_does_not_set_last_success_at() -> None:
    """Cancelled or failed finalizations must NOT populate last_success_at."""
    mgr = _manager_with_active_phase("erasing")
    mgr._finalize(state=EspFlashState.cancelled, error="cancelled")

    assert mgr._status.last_success_at is None


def test_to_dict_reflects_coherent_phase_after_finalize() -> None:
    """to_dict() on the status must expose the corrected phase, not a stale one."""
    mgr = _manager_with_active_phase("erasing")
    mgr._finalize(state=EspFlashState.failed, error="erase failed")

    d = mgr._status.to_dict()
    assert d["state"] == "failed"
    assert d["phase"] == "failed", (
        f"to_dict() must expose coherent phase after finalization, got {d['phase']!r}"
    )
