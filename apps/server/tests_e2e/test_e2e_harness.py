"""The per-worker e2e server keeps its ports when workers start side by side."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from tests_e2e import conftest
from tests_e2e.e2e_helpers import api_json

pytestmark = pytest.mark.e2e


def test_a_reserved_port_is_never_handed_out_but_its_listener_joins_it() -> None:
    with conftest._reserved_tcp_port() as port:
        for _ in range(2000):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind((conftest._HOST, 0))
                assert probe.getsockname()[1] != port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as plain:
            plain.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                plain.bind((conftest._HOST, port))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            listener.bind((conftest._HOST, port))
            listener.listen()
            listener.settimeout(5)
            for _ in range(20):
                with socket.create_connection((conftest._HOST, port), timeout=5):
                    accepted, _addr = listener.accept()
                    accepted.close()


def test_the_server_starts_on_fresh_udp_ports_when_another_process_took_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as taken:
        taken.bind((conftest._HOST, 0))
        taken_port = taken.getsockname()[1]
        # The first probe answers a port another process binds before the server.
        picks = iter([taken_port])
        free_udp_port = conftest._free_udp_port
        monkeypatch.setattr(conftest, "_free_udp_port", lambda: next(picks, 0) or free_udp_port())
        with conftest._running_server(tmp_path) as power:
            server = power.server
            assert taken_port not in {server.sim_data_port, server.sim_control_port}
            assert api_json(server.base_url, "/api/health")["startup_state"] == "ready"
    assert "Address already in use" in (tmp_path / "start-1" / "server.log").read_text()
