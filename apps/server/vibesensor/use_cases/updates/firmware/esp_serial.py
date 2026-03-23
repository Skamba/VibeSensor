"""Serial port discovery and selection helpers for ESP flashing."""

from __future__ import annotations

import logging

from vibesensor.use_cases.updates.firmware.esp_flash_types import SerialPortInfo, SerialPortProvider

LOGGER = logging.getLogger(__name__)

__all__ = ["PyserialPortProvider", "resolve_selected_port"]


class PyserialPortProvider(SerialPortProvider):
    """List serial ports using pyserial when available."""

    async def list_ports(self) -> list[SerialPortInfo]:
        try:
            from serial.tools import list_ports as serial_list_ports  # type: ignore[import-untyped]

            ports: list[SerialPortInfo] = []
            for row in serial_list_ports.comports():
                port = str(getattr(row, "device", "") or "").strip()
                if not port:
                    continue
                ports.append(
                    SerialPortInfo(
                        port=port,
                        description=str(getattr(row, "description", "") or ""),
                        vid=getattr(row, "vid", None),
                        pid=getattr(row, "pid", None),
                        serial_number=str(getattr(row, "serial_number", "") or "") or None,
                    ),
                )
            return ports
        except (ImportError, OSError):
            LOGGER.warning("Serial port enumeration failed; returning empty list.", exc_info=True)
            return []


def resolve_selected_port(configured: str | None, ports: list[SerialPortInfo]) -> str:
    """Choose a usable serial port or raise an actionable error."""

    if configured:
        if any(port.port == configured for port in ports):
            return configured
        raise ValueError(
            f"Selected serial port {configured} not found. Check cable/permissions and retry.",
        )
    if not ports:
        raise ValueError("No serial ports detected. Connect your ESP board and retry.")
    if len(ports) == 1:
        return ports[0].port
    usb_like = [port for port in ports if port.vid is not None or "usb" in port.description.lower()]
    if len(usb_like) == 1:
        return usb_like[0].port
    raise ValueError("Multiple serial ports detected. Select the ESP port explicitly.")
