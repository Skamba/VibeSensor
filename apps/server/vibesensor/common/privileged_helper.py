"""Client for the root-side privileged helper behind ``vibesensor-privileged.socket``.

``vibesensor.service`` runs with ``NoNewPrivileges=true``, so it cannot gain
root through sudo or other setuid programs. Root commands go over a Unix
socket instead. systemd owns the socket and starts one
``vibesensor-privileged@.service`` instance as root per connection. That
instance runs ``/usr/local/lib/vibesensor/vibesensor_privileged_helper.py``
(the root-owned copy of ``apps/server/root-helpers/`` that
``install_systemd_units.sh`` installs), which passes the request to the
allowlist wrapper the helper name selects (``update`` ->
``vibesensor_update_allowlist.sh``, ``obd`` -> ``vibesensor_obd_admin.py``).
Root never runs code from this package or its venv.

Protocol: one JSON request line ``{"helper", "args", "timeout_s"}``, answered
by one JSON response line ``{"returncode", "stdout", "stderr"}``.
"""

from __future__ import annotations

import asyncio
import json
import socket
from dataclasses import dataclass

from vibesensor.common.operational_errors import ExternalCommandError
from vibesensor.common.process_settings import privileged_socket_path

__all__ = [
    "OBD_HELPER",
    "UPDATE_HELPER",
    "PrivilegedHelperUnavailableError",
    "PrivilegedResult",
    "run_privileged",
    "run_privileged_async",
]

UPDATE_HELPER = "update"
OBD_HELPER = "obd"

_RESPONSE_LIMIT_BYTES = 512 * 1024
# The root side enforces timeout_s on the command; the extra margin covers
# systemd starting the helper instance and the response round trip.
_CONNECTION_MARGIN_S = 10.0


class PrivilegedHelperUnavailableError(ExternalCommandError):
    """The privileged helper socket could not be reached or answered badly."""


@dataclass(frozen=True, slots=True)
class PrivilegedResult:
    """Exit code and captured output of one privileged command."""

    returncode: int
    stdout: str
    stderr: str


def _request_line(helper: str, args: list[str], timeout_s: float) -> bytes:
    payload = {"helper": helper, "args": list(args), "timeout_s": timeout_s}
    return (json.dumps(payload) + "\n").encode()


def _result_from_line(line: bytes) -> PrivilegedResult:
    try:
        payload = json.loads(line)
    except ValueError:
        payload = None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("returncode"), int)
        or not isinstance(payload.get("stdout"), str)
        or not isinstance(payload.get("stderr"), str)
    ):
        raise PrivilegedHelperUnavailableError("Privileged helper returned an invalid response")
    return PrivilegedResult(
        returncode=payload["returncode"],
        stdout=payload["stdout"],
        stderr=payload["stderr"],
    )


def _unavailable(exc: BaseException) -> PrivilegedHelperUnavailableError:
    return PrivilegedHelperUnavailableError(
        f"Privileged helper socket {privileged_socket_path()} is unavailable ({exc}); "
        "re-run apps/server/scripts/install_pi.sh to install vibesensor-privileged.socket"
    )


def run_privileged(helper: str, args: list[str], *, timeout_s: float) -> PrivilegedResult:
    """Run *args* as root through *helper*'s allowlist wrapper (blocking)."""

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s + _CONNECTION_MARGIN_S)
        try:
            sock.connect(str(privileged_socket_path()))
        except OSError as exc:
            raise _unavailable(exc) from exc
        try:
            sock.sendall(_request_line(helper, args, timeout_s))
            with sock.makefile("rb") as stream:
                line = stream.readline(_RESPONSE_LIMIT_BYTES)
        except TimeoutError as exc:
            raise PrivilegedHelperUnavailableError(
                f"Privileged helper did not answer within {timeout_s + _CONNECTION_MARGIN_S:g}s"
            ) from exc
        except OSError as exc:
            raise _unavailable(exc) from exc
    return _result_from_line(line)


async def run_privileged_async(
    helper: str, args: list[str], *, timeout_s: float
) -> PrivilegedResult:
    """Run *args* as root through *helper*'s allowlist wrapper."""

    try:
        reader, writer = await asyncio.open_unix_connection(
            str(privileged_socket_path()), limit=_RESPONSE_LIMIT_BYTES
        )
    except OSError as exc:
        raise _unavailable(exc) from exc
    try:
        writer.write(_request_line(helper, args, timeout_s))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout_s + _CONNECTION_MARGIN_S)
    except TimeoutError as exc:
        raise PrivilegedHelperUnavailableError(
            f"Privileged helper did not answer within {timeout_s + _CONNECTION_MARGIN_S:g}s"
        ) from exc
    except ValueError as exc:
        raise PrivilegedHelperUnavailableError(
            "Privileged helper returned an invalid response"
        ) from exc
    except OSError as exc:
        raise _unavailable(exc) from exc
    finally:
        writer.close()
    return _result_from_line(line)
