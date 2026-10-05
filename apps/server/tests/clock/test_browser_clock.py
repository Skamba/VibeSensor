"""Stepping an unsynchronised system clock to the browser's clock."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.clock.browser_clock import (
    CLOCK_STEP_THRESHOLD_S,
    BrowserClockCorrector,
    ClockAction,
    kernel_clock_synchronized,
)

_SERVER_NOW_S = 1_700_000_000.0
_HOUR_AHEAD_MS = int((_SERVER_NOW_S + 3600.0) * 1000)


class _Clock:
    def __init__(
        self,
        *,
        synchronized: bool | None = False,
        recording: bool = False,
        error: OSError | None = None,
    ) -> None:
        self.synchronized = synchronized
        self.recording = recording
        self.error = error
        self.steps: list[float] = []

    def step(self, epoch_s: float) -> None:
        if self.error is not None:
            raise self.error
        self.steps.append(epoch_s)

    def corrector(
        self, *, state_path: Path | None = None, boot_id: str = "boot-a"
    ) -> BrowserClockCorrector:
        return BrowserClockCorrector(
            recording=lambda: self.recording,
            state_path=state_path,
            synchronized=lambda: self.synchronized,
            step=self.step,
            now=lambda: _SERVER_NOW_S,
            boot_id=lambda: boot_id,
        )


def test_unsynchronised_clock_is_stepped_once_to_the_browser_clock(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock()
    corrector = clock.corrector()

    with caplog.at_level(logging.WARNING, logger="vibesensor.clock.browser_clock"):
        first = corrector.report(_HOUR_AHEAD_MS)
    second = corrector.report(_HOUR_AHEAD_MS)

    assert (first.action, first.offset_s) == (ClockAction.STEPPED, 3600.0)
    assert clock.steps == [_SERVER_NOW_S + 3600.0]
    assert "Stepped the unsynchronised system clock by +3600.0 s" in caplog.text
    # Once per boot: a later report never steps again.
    assert second.action is ClockAction.ALREADY_STEPPED
    assert len(clock.steps) == 1


@pytest.mark.parametrize(
    ("clock", "browser_ms", "action"),
    [
        (_Clock(), int((_SERVER_NOW_S - CLOCK_STEP_THRESHOLD_S) * 1000), "within_threshold"),
        (_Clock(synchronized=True), _HOUR_AHEAD_MS, "ntp_synchronized"),
        (_Clock(synchronized=None), _HOUR_AHEAD_MS, "sync_state_unknown"),
        (_Clock(recording=True), _HOUR_AHEAD_MS, "recording"),
    ],
    ids=["small-offset", "ntp-synced", "sync-unknown", "recording"],
)
def test_clock_is_left_alone_unless_unsynchronised_idle_and_far_off(
    clock: _Clock, browser_ms: int, action: str
) -> None:
    result = clock.corrector().report(browser_ms)

    assert result.action == action
    assert clock.steps == []


def test_recording_only_defers_the_step() -> None:
    clock = _Clock(recording=True)
    corrector = clock.corrector()

    assert corrector.report(_HOUR_AHEAD_MS).action is ClockAction.RECORDING
    clock.recording = False
    assert corrector.report(_HOUR_AHEAD_MS).action is ClockAction.STEPPED


def test_missing_cap_sys_time_is_logged_once_and_not_retried(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock(error=PermissionError(1, "Operation not permitted"))
    corrector = clock.corrector()

    with caplog.at_level(logging.INFO, logger="vibesensor.clock.browser_clock"):
        results = [corrector.report(_HOUR_AHEAD_MS).action for _ in range(3)]

    assert results == [ClockAction.NOT_PERMITTED] * 3
    assert caplog.text.count("no CAP_SYS_TIME") == 1


_WITHIN_MS = int(_SERVER_NOW_S * 1000)


@pytest.mark.parametrize(
    ("clock", "reports_ms", "trusted"),
    [
        (_Clock(synchronized=True), [], True),
        (_Clock(), [], False),
        (_Clock(), [_WITHIN_MS], True),
        (_Clock(), [_HOUR_AHEAD_MS], True),
        (_Clock(), [_HOUR_AHEAD_MS, _HOUR_AHEAD_MS], True),
        (_Clock(recording=True), [_HOUR_AHEAD_MS], False),
        (_Clock(error=PermissionError(1, "Operation not permitted")), [_HOUR_AHEAD_MS], False),
        (_Clock(synchronized=None), [], True),
        (_Clock(synchronized=None), [_HOUR_AHEAD_MS], False),
    ],
    ids=[
        "ntp-synced",
        "unsynced-no-browser-yet",
        "browser-agrees",
        "stepped",
        "stepped-then-a-far-off-browser",
        "far-off-while-recording",
        "far-off-not-permitted",
        "sync-unknown-no-browser",
        "sync-unknown-far-off",
    ],
)
def test_clock_is_trusted_once_ntp_or_a_browser_vouches_for_it(
    clock: _Clock, reports_ms: list[int], trusted: bool
) -> None:
    corrector = clock.corrector()
    for report_ms in reports_ms:
        corrector.report(report_ms)

    assert corrector.clock_trusted() is trusted


def test_a_service_restart_keeps_this_boots_verdict_and_a_reboot_drops_it(
    tmp_path: Path,
) -> None:
    """Stepping leaves the kernel clock unsynchronised, so the verdict must outlive the process."""
    state_path = tmp_path / "clock_state.json"
    clock = _Clock()
    assert clock.corrector(state_path=state_path).report(_HOUR_AHEAD_MS).action is (
        ClockAction.STEPPED
    )

    # An update restarts the service before any browser reconnects.
    restarted = clock.corrector(state_path=state_path)
    assert restarted.clock_trusted() is True
    # Still one step per boot: a browser with a wrong clock cannot step it again.
    assert restarted.report(_HOUR_AHEAD_MS).action is ClockAction.ALREADY_STEPPED
    assert clock.steps == [_SERVER_NOW_S + 3600.0]

    # A reboot loses the time again (no RTC): no verdict until a browser reports.
    rebooted = clock.corrector(state_path=state_path, boot_id="boot-b")
    assert rebooted.clock_trusted() is False
    assert rebooted.report(_HOUR_AHEAD_MS).action is ClockAction.STEPPED


def test_a_restart_keeps_a_browser_verdict_against_the_clock(tmp_path: Path) -> None:
    """Unknown sync state is trusted by default, but not after a browser found it far off."""
    state_path = tmp_path / "clock_state.json"
    clock = _Clock(synchronized=None)
    clock.corrector(state_path=state_path).report(_HOUR_AHEAD_MS)

    assert clock.corrector(state_path=state_path).clock_trusted() is False


def test_kernel_sync_state_is_read_without_privileges() -> None:
    assert kernel_clock_synchronized() in (True, False, None)


# -- route ----------------------------------------------------------------------


@pytest.fixture
def _clock_client(fake_state):
    from vibesensor.web.browser_clock import create_browser_clock_routes

    clock = _Clock()
    app = FastAPI()
    app.include_router(create_browser_clock_routes(clock.corrector(), fake_state.ui_preferences))
    with TestClient(app) as client:
        yield client, clock, fake_state.ui_preferences


def test_route_steps_the_clock_and_stores_the_browser_time_zone(_clock_client) -> None:
    client, clock, preferences = _clock_client

    response = client.post(
        "/api/system/browser-clock",
        json={"epoch_ms": _HOUR_AHEAD_MS, "time_zone": "Europe/Amsterdam"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "action": "stepped",
        "offset_s": 3600.0,
        "time_zone": "Europe/Amsterdam",
    }
    assert clock.steps == [_SERVER_NOW_S + 3600.0]
    assert preferences.time_zone == "Europe/Amsterdam"


def test_route_keeps_the_stored_zone_when_the_browser_reports_an_unknown_one(
    _clock_client,
) -> None:
    client, _clock, preferences = _clock_client
    preferences.set_time_zone("Europe/Amsterdam")

    response = client.post(
        "/api/system/browser-clock",
        json={"epoch_ms": int(_SERVER_NOW_S * 1000), "time_zone": "Mars/Olympus_Mons"},
    )

    assert response.status_code == 200
    assert response.json()["action"] == "within_threshold"
    assert response.json()["time_zone"] == "Europe/Amsterdam"
