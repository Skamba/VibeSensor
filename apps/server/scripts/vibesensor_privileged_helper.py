#!/usr/bin/env python3
"""Root side of the VibeSensor privileged helper (``vibesensor-privileged@.service``).

``vibesensor.service`` runs with ``NoNewPrivileges=true``, so it cannot gain
root through sudo or any other setuid program. Instead, systemd listens on
``vibesensor-privileged.socket`` (owned by the service user, mode 0600). For
each connection, systemd starts one instance of this script as root, with the
connection as stdin and stdout.

The script reads one JSON request line::

    {"helper": "update" | "obd", "args": ["nmcli", ...], "timeout_s": 30}

It runs the allowlist wrapper that ``helper`` names, from this directory, with
``args``. Then it writes one JSON response line::

    {"returncode": 0, "stdout": "...", "stderr": "..."}

The wrappers stay the security boundary. This script only chooses which
wrapper runs, and never executes request arguments itself. It runs under the
system ``python3 -I``, so it must stay stdlib-only. The server-side client is
``vibesensor/common/privileged_helper.py``; keep the protocol in sync with it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HELPERS = {
    "update": SCRIPT_DIR / "vibesensor_update_allowlist.sh",
    "obd": SCRIPT_DIR / "vibesensor_obd_admin.py",
}
MAX_REQUEST_BYTES = 64 * 1024
MAX_TIMEOUT_S = 600
OUTPUT_LIMIT_CHARS = 64 * 1024


class RequestError(ValueError):
    """The request line is not a valid helper request."""


def parse_request(line: bytes) -> tuple[Path, list[str], float]:
    """Return (wrapper, args, timeout_s) for one request line, or raise RequestError."""

    if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
        raise RequestError("request must be one JSON line of at most 64 KiB")
    try:
        request = json.loads(line)
    except ValueError as exc:
        raise RequestError("request is not valid JSON") from exc
    if not isinstance(request, dict):
        raise RequestError("request must be a JSON object")
    helper = request.get("helper")
    wrapper = HELPERS.get(helper) if isinstance(helper, str) else None
    if wrapper is None:
        raise RequestError(f"unknown helper: {helper!r}")
    args = request.get("args")
    if not isinstance(args, list) or not all(
        isinstance(arg, str) and "\0" not in arg for arg in args
    ):
        raise RequestError("args must be a list of strings")
    timeout_s = request.get("timeout_s")
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not 0 < timeout_s <= MAX_TIMEOUT_S
    ):
        raise RequestError(f"timeout_s must be a number in (0, {MAX_TIMEOUT_S}]")
    return wrapper, args, float(timeout_s)


def _tail(data: bytes | str | None) -> str:
    if data is None:
        return ""
    text = data.decode(errors="replace") if isinstance(data, bytes) else data
    return text[-OUTPUT_LIMIT_CHARS:]


def run_request(wrapper: Path, args: list[str], timeout_s: float) -> dict[str, object]:
    """Run *wrapper* with *args* and return the response object."""

    try:
        completed = subprocess.run(
            [str(wrapper), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": 124,
            "stdout": _tail(exc.stdout),
            "stderr": f"Command timed out after {timeout_s:g}s",
        }
    except OSError as exc:
        return {"returncode": 126, "stdout": "", "stderr": f"Cannot run {wrapper.name}: {exc}"}
    return {
        "returncode": completed.returncode,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }


def main() -> int:
    line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    try:
        wrapper, args, timeout_s = parse_request(line)
    except RequestError as exc:
        response: dict[str, object] = {
            "returncode": 2,
            "stdout": "",
            "stderr": f"vibesensor_privileged_helper: {exc}",
        }
    else:
        response = run_request(wrapper, args, timeout_s)
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
