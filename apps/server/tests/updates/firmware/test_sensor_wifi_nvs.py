"""The flasher's NVS image carries the hotspot credentials the sensor firmware loads."""

from __future__ import annotations

import pytest
from test_support.firmware_bundles import DEFAULT_PARTITION_TABLE, partition_entry
from test_support.nvs_reader import read_nvs_strings

from vibesensor.updates.firmware.sensor_wifi_nvs import build_wifi_nvs_image, nvs_partition_span


def test_nvs_partition_span_reads_the_data_nvs_entry() -> None:
    assert nvs_partition_span(DEFAULT_PARTITION_TABLE) == (0x9000, 0x5000)


def test_nvs_partition_span_rejects_a_table_without_nvs() -> None:
    table = partition_entry("app0", 0x00, 0x10, 0x10000, 0x140000) + b"\xff" * 32
    with pytest.raises(ValueError, match="no NVS partition"):
        nvs_partition_span(table)


def test_image_holds_ssid_and_psk_in_the_firmware_namespace() -> None:
    image = build_wifi_nvs_image(ssid="Workshop", psk="secret-psk", size=0x5000)

    assert len(image) == 0x5000
    assert read_nvs_strings(image) == {"vs_wifi": {"ssid": "Workshop", "psk": "secret-psk"}}


def test_open_hotspot_stores_no_psk() -> None:
    image = build_wifi_nvs_image(ssid="VibeSensor", psk="", size=0x5000)

    assert read_nvs_strings(image) == {"vs_wifi": {"ssid": "VibeSensor"}}


@pytest.mark.parametrize(
    ("ssid", "psk", "size", "message"),
    [
        pytest.param("", "", 0x5000, "SSID", id="empty-ssid"),
        pytest.param("x" * 33, "", 0x5000, "SSID", id="long-ssid"),
        pytest.param("VibeSensor", "p" * 65, 0x5000, "password", id="long-psk"),
        pytest.param("VibeSensor", "", 0x2000, "NVS partition size", id="tiny-partition"),
    ],
)
def test_invalid_credentials_or_partition_are_rejected(
    ssid: str, psk: str, size: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_wifi_nvs_image(ssid=ssid, psk=psk, size=size)
