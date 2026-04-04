from unittest.mock import MagicMock

from vibesensor.adapters.obd.runtime_services import (
    ObdRuntime,
    ObdRuntimeConnection,
    ObdRuntimeControl,
    ObdRuntimeObservation,
    build_obd_runtime,
)


def test_build_obd_runtime_groups_services_by_role() -> None:
    runtime = build_obd_runtime(
        admin_client=MagicMock(),
        session_factory=MagicMock(),
    )

    assert isinstance(runtime, ObdRuntime)
    assert isinstance(runtime.observation, ObdRuntimeObservation)
    assert isinstance(runtime.control, ObdRuntimeControl)
    assert isinstance(runtime.connection, ObdRuntimeConnection)
    assert runtime.observation.facts is not None
    assert runtime.observation.projection is not None
    assert runtime.control.settings is not None
    assert runtime.control.admin is not None
    assert runtime.connection.runner is not None
