from __future__ import annotations

from vibesensor.adapters.obd.connection_plan import (
    ObdConnectionLoopSnapshot,
    ObdConnectionStepKind,
    plan_connection_step,
)
from vibesensor.domain import SpeedSourceKind


def test_connection_plan_idles_when_obd_is_not_selected() -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(
            selected_source=SpeedSourceKind.GPS,
            configured_mac="00:11",
            configured_name="OBD",
            has_session=True,
            session_device_mac="00:11",
        ),
        idle_poll_s=1.0,
    )

    assert step.kind is ObdConnectionStepKind.IDLE
    assert step.close_session is True
    assert step.sleep_s == 1.0


def test_connection_plan_requires_configured_adapter_before_connecting() -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(
            selected_source=SpeedSourceKind.OBD2,
            configured_mac=None,
            configured_name=None,
            has_session=False,
            session_device_mac=None,
        ),
        idle_poll_s=1.0,
    )

    assert step.kind is ObdConnectionStepKind.MISSING_CONFIG
    assert step.error == "No configured Bluetooth OBD adapter"


def test_connection_plan_replaces_session_when_configured_device_changes() -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(
            selected_source=SpeedSourceKind.OBD2,
            configured_mac="00:11",
            configured_name="OBD",
            has_session=True,
            session_device_mac="22:33",
        ),
        idle_poll_s=1.0,
    )

    assert step.kind is ObdConnectionStepKind.REPLACE_SESSION
    assert step.close_session is True


def test_connection_plan_waits_until_poll_is_due() -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(
            selected_source=SpeedSourceKind.OBD2,
            configured_mac="00:11",
            configured_name="OBD",
            has_session=True,
            session_device_mac="00:11",
            poll_wait_s=0.25,
        ),
        idle_poll_s=1.0,
    )

    assert step.kind is ObdConnectionStepKind.WAIT
    assert step.sleep_s == 0.25


def test_connection_plan_polls_when_due_with_matching_session() -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(
            selected_source=SpeedSourceKind.OBD2,
            configured_mac="00:11",
            configured_name="OBD",
            has_session=True,
            session_device_mac="00:11",
            poll_wait_s=0.0,
        ),
        idle_poll_s=1.0,
    )

    assert step.kind is ObdConnectionStepKind.POLL
