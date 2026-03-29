"""Low-level Bluetooth RFCOMM helpers for ELM/STN OBD adapters."""

from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable

from vibesensor.adapters.obd.common import bluetooth_mac_address

__all__ = [
    "Elm327Session",
    "ObdTransportError",
    "elm_response_has_no_data",
    "normalize_elm_response",
    "parse_pid_010c_rpm",
    "parse_pid_010d_speed_kmh",
]

_NO_DATA_MARKERS = (
    "NO DATA",
    "STOPPED",
    "UNABLE TO CONNECT",
    "BUS BUSY",
    "BUFFER FULL",
    "DATA ERROR",
)

_HEX_RE = re.compile(r"[^0-9A-F]")
_AF_BLUETOOTH = getattr(socket, "AF_BLUETOOTH", 31)
_BTPROTO_RFCOMM = getattr(socket, "BTPROTO_RFCOMM", 3)


class ObdTransportError(RuntimeError):
    """Raised when the RFCOMM/ELM transport fails."""


SocketFactory = Callable[[int, int, int], socket.socket]


def normalize_elm_response(command: str, raw_response: bytes | str) -> str:
    """Strip prompts, banners, and command echo from a raw ELM response."""
    if isinstance(raw_response, bytes):
        text = raw_response.decode("ascii", errors="ignore")
    else:
        text = raw_response
    lines = [line.strip() for line in re.split(r"[\r\n]+", text.replace(">", "\n")) if line.strip()]
    command_compact = re.sub(r"\s+", "", command).upper()
    cleaned: list[str] = []
    for line in lines:
        compact = re.sub(r"[^0-9A-FA-Z]", "", line.upper())
        if compact == command_compact:
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def elm_response_has_no_data(response_text: str) -> bool:
    """Whether *response_text* represents an ECU/no-data condition."""
    upper = response_text.upper()
    return any(marker in upper for marker in _NO_DATA_MARKERS)


def _normalized_hex_payload(response_text: str) -> str:
    return _HEX_RE.sub("", response_text.upper())


def parse_pid_010d_speed_kmh(response_text: str) -> float | None:
    """Parse PID ``010D`` (vehicle speed) from a normalized ELM response."""
    if elm_response_has_no_data(response_text):
        return None
    payload = _normalized_hex_payload(response_text)
    marker = "410D"
    index = payload.find(marker)
    if index < 0 or len(payload) < index + len(marker) + 2:
        return None
    return float(int(payload[index + len(marker) : index + len(marker) + 2], 16))


def parse_pid_010c_rpm(response_text: str) -> float | None:
    """Parse PID ``010C`` (engine RPM) from a normalized ELM response."""
    if elm_response_has_no_data(response_text):
        return None
    payload = _normalized_hex_payload(response_text)
    marker = "410C"
    index = payload.find(marker)
    if index < 0 or len(payload) < index + len(marker) + 4:
        return None
    raw_value = int(payload[index + len(marker) : index + len(marker) + 4], 16)
    return float(raw_value) / 4.0


class Elm327Session:
    """Blocking RFCOMM session for a paired ELM/STN adapter."""

    __slots__ = ("_read_timeout_s", "_socket", "_socket_factory")

    def __init__(
        self,
        *,
        read_timeout_s: float = 2.0,
        socket_factory: SocketFactory | None = None,
    ) -> None:
        self._read_timeout_s = max(0.2, float(read_timeout_s))
        self._socket_factory = socket.socket if socket_factory is None else socket_factory
        self._socket: socket.socket | None = None

    def connect(self, mac_address: str, channel: int) -> None:
        sock = self._socket_factory(_AF_BLUETOOTH, socket.SOCK_STREAM, _BTPROTO_RFCOMM)
        sock.settimeout(self._read_timeout_s)
        try:
            sock.connect((bluetooth_mac_address(mac_address), int(channel)))
        except OSError as exc:
            sock.close()
            raise ObdTransportError(f"RFCOMM connect failed: {exc}") from exc
        self._socket = sock
        self._drain_input()

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            sock.close()
        except OSError:
            return

    def initialize(self) -> None:
        self._drain_input()
        self.request("ATZ", timeout_s=4.0)
        time.sleep(0.4)
        for command in ("ATE0", "ATL0", "ATS0", "ATH0", "ATSP0", "ATAT2"):
            self.request(command, timeout_s=2.0)

    def request(self, command: str, *, timeout_s: float | None = None) -> str:
        sock = self._require_socket()
        previous_timeout = sock.gettimeout()
        try:
            sock.settimeout(self._read_timeout_s if timeout_s is None else float(timeout_s))
            self._drain_input()
            payload = f"{command.strip().upper()}\r".encode("ascii")
            sock.sendall(payload)
            raw = self._read_until_prompt()
        except OSError as exc:
            raise ObdTransportError(f"ELM327 request failed: {exc}") from exc
        finally:
            sock.settimeout(previous_timeout)
        return normalize_elm_response(command, raw)

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise ObdTransportError("ELM327 session is not connected")
        return self._socket

    def _drain_input(self) -> None:
        sock = self._require_socket()
        previous_timeout = sock.gettimeout()
        try:
            sock.settimeout(0.05)
            while True:
                try:
                    chunk = sock.recv(512)
                except TimeoutError:
                    return
                if not chunk:
                    return
                if len(chunk) < 512:
                    return
        finally:
            sock.settimeout(previous_timeout)

    def _read_until_prompt(self) -> bytes:
        sock = self._require_socket()
        chunks: list[bytes] = []
        while True:
            try:
                chunk = sock.recv(512)
            except TimeoutError as exc:
                raise ObdTransportError("Timed out waiting for OBD response prompt") from exc
            if not chunk:
                raise ObdTransportError("Bluetooth OBD adapter closed the RFCOMM socket")
            chunks.append(chunk)
            if b">" in chunk:
                return b"".join(chunks)
