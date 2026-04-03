from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.adapters.obd.admin_state import observe_configured_obd_device
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.shared.operational_errors import ExternalCommandError


def test_observe_configured_obd_device_skips_lookup_without_configured_mac() -> None:
    admin_client = MagicMock()

    observation = observe_configured_obd_device(
        admin_client=admin_client,
        configured_mac=None,
    )

    assert observation.snapshot is None
    assert observation.helper_error is None
    admin_client.device_info.assert_not_called()


def test_observe_configured_obd_device_returns_helper_error_for_operational_failure() -> None:
    admin_client = MagicMock()
    admin_client.device_info.side_effect = ExternalCommandError("sudo helper missing")

    observation = observe_configured_obd_device(
        admin_client=admin_client,
        configured_mac="00043e5a4a4d",
    )

    assert observation.snapshot is None
    assert observation.helper_error == "sudo helper missing"


def test_observe_configured_obd_device_returns_snapshot() -> None:
    admin_client = MagicMock()
    admin_client.device_info.return_value = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
    )

    observation = observe_configured_obd_device(
        admin_client=admin_client,
        configured_mac="00043e5a4a4d",
    )

    assert observation.snapshot == admin_client.device_info.return_value
    assert observation.helper_error is None
