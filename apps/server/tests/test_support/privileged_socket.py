"""Serve the real root-side privileged helper the way systemd's ``Accept=yes`` does.

Each connection to the socket runs ``root-helpers/vibesensor_privileged_helper.py``
with the connection as stdin and stdout, exactly like
``vibesensor-privileged@.service``, but as the test user instead of root.
"""

from __future__ import annotations

import contextlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from test_support.root_helpers import ROOT_HELPERS_DIR

__all__ = ["HELPER_SCRIPT", "serve_privileged_helper"]

HELPER_SCRIPT = ROOT_HELPERS_DIR / "vibesensor_privileged_helper.py"


def _accept_loop(server: socket.socket, helper_script: Path) -> None:
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            subprocess.run(
                [sys.executable, "-I", str(helper_script)],
                stdin=conn.fileno(),
                stdout=conn.fileno(),
                check=False,
            )


@contextmanager
def serve_privileged_helper(helper_script: Path = HELPER_SCRIPT) -> Iterator[Path]:
    """Yield a socket path served by *helper_script* (one process per connection)."""

    # AF_UNIX paths are limited to ~108 bytes, so avoid pytest's long tmp_path.
    socket_dir = Path(tempfile.mkdtemp(prefix="vs-priv-"))
    socket_path = socket_dir / "helper.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen()
    thread = threading.Thread(target=_accept_loop, args=(server, helper_script), daemon=True)
    thread.start()
    try:
        yield socket_path
    finally:
        with contextlib.suppress(OSError):
            server.shutdown(socket.SHUT_RDWR)
        server.close()
        thread.join(timeout=5)
        shutil.rmtree(socket_dir, ignore_errors=True)
