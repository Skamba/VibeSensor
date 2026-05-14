from __future__ import annotations

import pytest

from vibesensor.domain import Car, Finding, Sensor, SensorPlacement, SpeedSource
from vibesensor.shared.boundaries.reporting.document import Report


@pytest.mark.parametrize(
    ("factory", "attribute", "new_value"),
    [
        pytest.param(
            lambda: SpeedSource(kind="manual", manual_speed_kmh=80.0),
            "kind",
            "gps",
            id="speed-source",
        ),
        pytest.param(
            lambda: SensorPlacement.from_code("trunk"),
            "code",
            "engine_bay",
            id="sensor-placement",
        ),
        pytest.param(
            lambda: Sensor(sensor_id="aabbccddeeff"),
            "name",
            "new",
            id="sensor",
        ),
        pytest.param(lambda: Car(), "name", "new", id="car"),
        pytest.param(lambda: Finding(finding_id="F001"), "finding_id", "F002", id="finding"),
        pytest.param(lambda: Report(run_id="abc"), "title", "new", id="report"),
    ],
)
def test_domain_objects_are_immutable(factory, attribute: str, new_value: object) -> None:
    obj = factory()

    with pytest.raises(AttributeError):
        setattr(obj, attribute, new_value)
