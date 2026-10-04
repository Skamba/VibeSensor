"""The server-side privileged helper client against the real root-side helper script."""

from __future__ import annotations

import shutil
import socket
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_support.privileged_socket import serve_privileged_helper

from vibesensor.common.privileged_helper import (
    UPDATE_HELPER,
    PrivilegedHelperUnavailableError,
    PrivilegedResult,
    run_privileged,
    run_privileged_async,
)


@pytest.fixture
def helper_socket(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    with serve_privileged_helper() as socket_path:
        monkeypatch.setenv("VIBESENSOR_PRIVILEGED_SOCKET", str(socket_path))
        yield socket_path


def test_run_privileged_returns_the_allowlisted_command_result(helper_socket: Path) -> None:
    del helper_socket
    assert run_privileged(UPDATE_HELPER, ["python3", "-c", "pass"], timeout_s=10) == (
        PrivilegedResult(returncode=0, stdout="", stderr="")
    )


@pytest.mark.asyncio
async def test_run_privileged_async_relays_the_allowlist_rejection(helper_socket: Path) -> None:
    del helper_socket
    result = await run_privileged_async(UPDATE_HELPER, ["bash", "-c", "id"], timeout_s=10)

    assert result.returncode == 126
    assert result.stdout == ""
    assert "command 'bash' is not allowed" in result.stderr


@pytest.mark.asyncio
async def test_missing_socket_raises_unavailable_with_install_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBESENSOR_PRIVILEGED_SOCKET", str(tmp_path / "missing.sock"))

    with pytest.raises(PrivilegedHelperUnavailableError, match="install_pi.sh"):
        run_privileged(UPDATE_HELPER, ["python3", "-c", "pass"], timeout_s=5)
    with pytest.raises(PrivilegedHelperUnavailableError, match="missing.sock is unavailable"):
        await run_privileged_async(UPDATE_HELPER, ["python3", "-c", "pass"], timeout_s=5)


def _serve_once(socket_path: Path, reply: bytes) -> threading.Thread:
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen()

    def _answer() -> None:
        with server, server.accept()[0] as conn:
            conn.recv(65536)
            conn.sendall(reply)

    thread = threading.Thread(target=_answer, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("reply", [b"", b"not json\n", b'{"returncode": "0"}\n'])
def test_malformed_helper_reply_is_reported_as_invalid_response(
    reply: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_path = Path(tempfile.mkdtemp(prefix="vs-priv-")) / "helper.sock"
    monkeypatch.setenv("VIBESENSOR_PRIVILEGED_SOCKET", str(socket_path))
    thread = _serve_once(socket_path, reply)
    try:
        with pytest.raises(PrivilegedHelperUnavailableError, match="invalid response"):
            run_privileged(UPDATE_HELPER, ["python3", "-c", "pass"], timeout_s=5)
    finally:
        thread.join(timeout=5)
        shutil.rmtree(socket_path.parent)
