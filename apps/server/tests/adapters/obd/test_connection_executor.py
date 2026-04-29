from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from test_support.obd_runtime import (
    FakeClock,
    build_connected_obd_runtime_parts,
    build_obd_runtime_parts,
)

from vibesensor.adapters.obd.connection_executor import ObdConnectionLoopState
from vibesensor.adapters.obd.connection_plan import ObdConnectionStep, ObdConnectionStepKind
from vibesensor.adapters.obd.elm327 import ObdTransportError


@pytest.mark.asyncio
async def test_executor_closes_replaced_session_before_returning_to_planning() -> None:
    clock = FakeClock()
    parts = build_connected_obd_runtime_parts(clock=clock)

    state = ObdConnectionLoopState(
        session=parts.session,
        session_device_mac="00043e5a4a4d",
        reconnect_delay_s=4.0,
    )
    next_state = await parts.executor.execute(
        state=state,
        step=ObdConnectionStep(
            kind=ObdConnectionStepKind.REPLACE_SESSION,
            close_session=True,
        ),
    )

    parts.session.close.assert_called_once_with()
    assert next_state.session is None
    assert next_state.session_device_mac is None
    assert next_state.reconnect_delay_s == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_executor_marks_disconnected_and_backs_off_after_connect_failure() -> None:
    clock = FakeClock()
    admin_client = MagicMock()
    admin_client.device_info.side_effect = OSError("rfcomm busy")
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    parts = build_obd_runtime_parts(
        clock=clock,
        admin_client=admin_client,
        sleep=record_sleep,
    )
    next_state = await parts.executor.execute(
        state=ObdConnectionLoopState(reconnect_delay_s=2.0),
        step=ObdConnectionStep(
            kind=ObdConnectionStepKind.CONNECT,
            mac_address="00043e5a4a4d",
            configured_name="OBDLink MX+",
        ),
    )

    status = parts.projection.status_snapshot()
    assert sleeps == [2.0]
    assert status.connection_state == "disconnected"
    assert status.last_error == "rfcomm busy"
    assert next_state.session is None
    assert next_state.session_device_mac is None
    assert next_state.reconnect_delay_s == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_executor_connect_step_marks_connected_without_closing_initialized_session() -> None:
    clock = FakeClock()
    parts = build_obd_runtime_parts(clock=clock)

    next_state = await parts.executor.execute(
        state=ObdConnectionLoopState(),
        step=ObdConnectionStep(
            kind=ObdConnectionStepKind.CONNECT,
            mac_address="00043e5a4a4d",
            configured_name="OBDLink MX+",
        ),
    )

    status = parts.projection.status_snapshot()
    assert next_state.session is parts.session
    assert next_state.session_device_mac == "00043e5a4a4d"
    assert next_state.reconnect_delay_s == pytest.approx(1.0)
    parts.session.initialize.assert_called_once_with()
    parts.session.close.assert_not_called()
    assert status.connection_state == "connected"
    assert status.device_mac == "00043e5a4a4d"
    assert status.connected is True


@pytest.mark.asyncio
async def test_executor_connect_step_backs_off_after_initialize_transport_error() -> None:
    clock = FakeClock()
    session = MagicMock()
    session.initialize.side_effect = ObdTransportError("no prompt from adapter")
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    parts = build_obd_runtime_parts(clock=clock, session=session, sleep=record_sleep)

    next_state = await parts.executor.execute(
        state=ObdConnectionLoopState(reconnect_delay_s=2.0),
        step=ObdConnectionStep(
            kind=ObdConnectionStepKind.CONNECT,
            mac_address="00043e5a4a4d",
            configured_name="OBDLink MX+",
        ),
    )

    status = parts.projection.status_snapshot()
    session.close.assert_called_once_with()
    assert sleeps == [2.0]
    assert status.connection_state == "disconnected"
    assert status.last_error == "no prompt from adapter"
    assert next_state.session is None
    assert next_state.session_device_mac is None
    assert next_state.reconnect_delay_s == pytest.approx(4.0)


@pytest.mark.asyncio
async def test_executor_connect_step_closes_session_and_propagates_unexpected_runtime_error() -> (
    None
):
    clock = FakeClock()
    session = MagicMock()
    session.initialize.side_effect = RuntimeError("session bug")
    parts = build_obd_runtime_parts(clock=clock, session=session)

    with pytest.raises(RuntimeError, match="session bug"):
        await parts.executor.execute(
            state=ObdConnectionLoopState(),
            step=ObdConnectionStep(
                kind=ObdConnectionStepKind.CONNECT,
                mac_address="00043e5a4a4d",
                configured_name="OBDLink MX+",
            ),
        )

    session.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_executor_closes_session_and_backs_off_after_poll_connection_loss() -> None:
    clock = FakeClock()
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    parts = build_connected_obd_runtime_parts(clock=clock, sleep=record_sleep)

    def request(command: str, *, timeout_s: float | None = None) -> str:
        del command, timeout_s
        raise ObdTransportError("Session is not connected")

    parts.session.request.side_effect = request

    next_state = await parts.executor.execute(
        state=ObdConnectionLoopState(
            session=parts.session,
            session_device_mac="00043e5a4a4d",
            reconnect_delay_s=4.0,
        ),
        step=ObdConnectionStep(kind=ObdConnectionStepKind.POLL),
    )

    status = parts.projection.status_snapshot()
    parts.session.close.assert_called_once_with()
    assert sleeps == [4.0]
    assert status.connection_state == "disconnected"
    assert status.last_error == "PID 010C request failed: Session is not connected"
    assert next_state.session is None
    assert next_state.session_device_mac is None
    assert next_state.reconnect_delay_s == pytest.approx(8.0)
