"""NVS partition image that hands the hotspot's Wi-Fi credentials to a sensor.

The firmware reads ``ssid``/``psk`` from the Preferences namespace ``vs_wifi``
(``firmware/esp/src/runtime_wifi.*``) and only falls back to its compile-time
defaults when they are absent. The Pi flasher writes this image over the
bundle's ``nvs`` partition, so a sensor flashed from the Pi joins the hotspot
as currently configured (``ap.ssid`` / ``ap.psk``).
"""

from __future__ import annotations

import io

__all__ = ["build_wifi_nvs_image", "nvs_partition_span"]

WIFI_PREFS_NAMESPACE = "vs_wifi"
_SSID_MAX_BYTES = 32
_PSK_MAX_BYTES = 64

_PARTITION_ENTRY_SIZE = 32
_PARTITION_MAGIC = b"\xaa\x50"
_PARTITION_TYPE_DATA = 0x01
_PARTITION_SUBTYPE_NVS = 0x02
_NVS_PAGE_SIZE = 4096


def nvs_partition_span(partition_table: bytes) -> tuple[int, int]:
    """Return ``(offset, size)`` of the ``nvs`` data partition in an ESP-IDF table."""
    for start in range(0, len(partition_table) - _PARTITION_ENTRY_SIZE + 1, _PARTITION_ENTRY_SIZE):
        entry = partition_table[start : start + _PARTITION_ENTRY_SIZE]
        if entry[:2] != _PARTITION_MAGIC:
            break
        if entry[2] == _PARTITION_TYPE_DATA and entry[3] == _PARTITION_SUBTYPE_NVS:
            offset = int.from_bytes(entry[4:8], "little")
            size = int.from_bytes(entry[8:12], "little")
            return offset, size
    raise ValueError("Firmware partition table has no NVS partition for the sensor Wi-Fi settings")


def build_wifi_nvs_image(*, ssid: str, psk: str, size: int) -> bytes:
    """Build an NVS partition image of *size* bytes holding the hotspot credentials."""
    if not ssid or len(ssid.encode()) > _SSID_MAX_BYTES:
        raise ValueError(f"Hotspot SSID must be 1-{_SSID_MAX_BYTES} bytes to flash sensors")
    if len(psk.encode()) > _PSK_MAX_BYTES:
        raise ValueError(f"Hotspot password must be at most {_PSK_MAX_BYTES} bytes")
    if size < 3 * _NVS_PAGE_SIZE or size % _NVS_PAGE_SIZE:
        raise ValueError(f"Unsupported NVS partition size {size:#x}")
    try:
        # Imported here: like esptool, it ships in the ``esp`` extra only.
        from esp_idf_nvs_partition_gen import nvs_partition_gen
    except ImportError as exc:
        raise ValueError("esp-idf-nvs-partition-gen is not installed (vibesensor[esp])") from exc
    out = io.BytesIO()
    # The generator keeps one page in reserve on top of the size it is given.
    nvs = nvs_partition_gen.nvs_open(out, size - _NVS_PAGE_SIZE, nvs_partition_gen.Page.VERSION2)
    nvs_partition_gen.write_entry(nvs, WIFI_PREFS_NAMESPACE, "namespace", "", "")
    nvs_partition_gen.write_entry(nvs, "ssid", "data", "string", ssid)
    if psk:
        nvs_partition_gen.write_entry(nvs, "psk", "data", "string", psk)
    nvs_partition_gen.nvs_close(nvs)
    image = out.getvalue()
    if len(image) != size:
        raise ValueError(f"NVS image is {len(image):#x} bytes, expected {size:#x}")
    return image
