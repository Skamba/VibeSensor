"""Root-side privileged helper: request validation, dispatch, and timeouts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_support.privileged_socket import HELPER_SCRIPT
from test_support.root_helpers import load_root_helper


def _run_helper(stdin: bytes) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, "-I", str(HELPER_SCRIPT)],
        input=stdin,
        capture_output=True,
        check=True,
        timeout=30,
    )
    assert completed.stderr == b""
    return json.loads(completed.stdout)


def test_helpers_name_existing_wrappers_next_to_the_script() -> None:
    module = load_root_helper("vibesensor_privileged_helper.py")

    assert set(module.HELPERS) == {"update", "obd"}
    for wrapper in module.HELPERS.values():
        assert wrapper.parent == HELPER_SCRIPT.parent
        assert wrapper.is_file()


def test_update_request_runs_through_the_allowlist_wrapper() -> None:
    allowed = _run_helper(
        b'{"helper": "update", "args": ["python3", "-c", "pass"], "timeout_s": 10}\n'
    )
    rejected = _run_helper(b'{"helper": "update", "args": ["id"], "timeout_s": 10}\n')

    assert allowed == {"returncode": 0, "stdout": "", "stderr": ""}
    assert rejected["returncode"] == 126
    assert "command 'id' is not allowed" in str(rejected["stderr"])


@pytest.mark.parametrize(
    ("line", "message"),
    [
        (b"", "one JSON line"),
        (b'{"helper": "update", "args": [], "timeout_s": 1}', "one JSON line"),
        (b"[1]\n", "JSON object"),
        (b"{nope\n", "not valid JSON"),
        (b'{"helper": "sh", "args": [], "timeout_s": 1}\n', "unknown helper: 'sh'"),
        (b'{"helper": ["update"], "args": [], "timeout_s": 1}\n', "unknown helper"),
        (b'{"helper": "update", "args": "id", "timeout_s": 1}\n', "list of strings"),
        (b'{"helper": "update", "args": [1], "timeout_s": 1}\n', "list of strings"),
        (b'{"helper": "update", "args": [], "timeout_s": 0}\n', "timeout_s"),
        (b'{"helper": "update", "args": [], "timeout_s": 601}\n', "timeout_s"),
        (b'{"helper": "update", "args": [], "timeout_s": true}\n', "timeout_s"),
    ],
)
def test_invalid_requests_are_refused_without_running_anything(line: bytes, message: str) -> None:
    response = _run_helper(line)

    assert response["returncode"] == 2
    assert response["stdout"] == ""
    assert message in str(response["stderr"])


def test_oversized_request_is_refused() -> None:
    padding = "x" * (64 * 1024)
    line = json.dumps({"helper": "update", "args": [padding], "timeout_s": 1}).encode() + b"\n"

    response = _run_helper(line)

    assert response["returncode"] == 2
    assert "64 KiB" in str(response["stderr"])


def test_run_request_enforces_the_timeout_and_keeps_output_tail(tmp_path: Path) -> None:
    module = load_root_helper("vibesensor_privileged_helper.py")
    slow = tmp_path / "slow.sh"
    slow.write_text("#!/bin/sh\necho started\nexec sleep 30\n", encoding="utf-8")
    slow.chmod(0o755)

    response = module.run_request(slow, [], 0.5)

    assert response == {
        "returncode": 124,
        "stdout": "started\n",
        "stderr": "Command timed out after 0.5s",
    }


def test_run_request_reports_an_unrunnable_wrapper(tmp_path: Path) -> None:
    module = load_root_helper("vibesensor_privileged_helper.py")

    response = module.run_request(tmp_path / "missing.sh", [], 1)

    assert response["returncode"] == 126
    assert "Cannot run missing.sh" in str(response["stderr"])
