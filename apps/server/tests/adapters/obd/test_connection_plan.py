from __future__ import annotations

import pytest

from vibesensor.adapters.obd.connection_plan import (
    ObdConnectionLoopSnapshot,
    ObdConnectionStepKind,
    plan_connection_step,
)
from vibesensor.domain.speed_source import SpeedSourceKind

_CONNECTED_OBD: dict[str, object] = {
    "selected_source": SpeedSourceKind.OBD2,
    "configured_mac": "00:11",
    "configured_name": "OBD",
    "has_session": True,
    "session_device_mac": "00:11",
}


@pytest.mark.parametrize(
    ("snapshot_overrides", "expected_kind", "expected_fields"),
    [
        pytest.param(
            {"selected_source": SpeedSourceKind.GPS},
            ObdConnectionStepKind.IDLE,
            {"close_session": True, "sleep_s": 1.0},
            id="idles-when-obd-not-selected",
        ),
        pytest.param(
            {
                "configured_mac": None,
                "configured_name": None,
                "has_session": False,
                "session_device_mac": None,
            },
            ObdConnectionStepKind.MISSING_CONFIG,
            {"error": "No configured Bluetooth OBD adapter"},
            id="requires-configured-adapter",
        ),
        pytest.param(
            {"session_device_mac": "22:33"},
            ObdConnectionStepKind.REPLACE_SESSION,
            {"close_session": True},
            id="replaces-session-when-device-changes",
        ),
        pytest.param(
            {"poll_wait_s": 0.25},
            ObdConnectionStepKind.WAIT,
            {"sleep_s": 0.25},
            id="waits-until-poll-due",
        ),
        pytest.param(
            {"poll_wait_s": 0.0},
            ObdConnectionStepKind.POLL,
            {},
            id="polls-when-due-with-matching-session",
        ),
    ],
)
def test_plan_connection_step(
    snapshot_overrides: dict[str, object],
    expected_kind: ObdConnectionStepKind,
    expected_fields: dict[str, object],
) -> None:
    step = plan_connection_step(
        ObdConnectionLoopSnapshot(**{**_CONNECTED_OBD, **snapshot_overrides}),
        idle_poll_s=1.0,
    )

    assert step.kind is expected_kind
    assert {name: getattr(step, name) for name in expected_fields} == expected_fields
