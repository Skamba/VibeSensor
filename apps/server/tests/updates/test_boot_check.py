"""Boot check: a switched-to slot is confirmed when healthy and reverted otherwise."""

from __future__ import annotations

import json
import signal
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from test_support.venv_slots import make_legacy_venv

from vibesensor.updates.boot_check import (
    MAX_CANDIDATE_STARTS,
    PENDING_FILE,
    REVERTED_FILE,
    SERVER_APP,
    PendingBoot,
    is_healthy,
    prepare_boot,
    read_pending,
    supervise,
)
from vibesensor.updates.venv_slots import VenvSlots

_HEALTH_URL = "http://127.0.0.1:9/api/health"


def _slots_with_candidate(tmp_path: Path, *, app_script: str | None = None) -> VenvSlots:
    """Slot 1.0 (adopted) and candidate 2.0, switched to 2.0 with a pending boot check."""
    root = make_legacy_venv(tmp_path / ".venv", server_script=app_script)
    slots = VenvSlots(root)
    slots.adopt("1.0")
    slots.clone_slot("1.0", "2.0")
    if app_script is not None:
        for name, label in (("1.0", "previous"), ("2.0", "candidate")):
            app = slots.slot_dir(name) / "bin" / SERVER_APP
            app.write_text(app_script.replace("LABEL", label), encoding="utf-8")
    slots.activate("2.0", health_url=_HEALTH_URL)
    return slots


def _write_pending(slots: VenvSlots, **changes: object) -> None:
    data = json.loads((slots.root / PENDING_FILE).read_text())
    data.update(changes)
    (slots.root / PENDING_FILE).write_text(json.dumps(data))


def test_no_pending_marker_runs_the_slot_unchecked(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path)
    (slots.root / PENDING_FILE).unlink()

    assert prepare_boot(slots.root, "2.0") == ("2.0", None)


def test_first_candidate_start_is_counted_and_supervised(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path)

    run_slot, pending = prepare_boot(slots.root, "2.0")

    assert run_slot == "2.0"
    assert pending is not None and pending.starts == 1
    assert read_pending(slots.root) == pending


def test_stale_marker_for_a_slot_that_never_became_active_is_dropped(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path)

    assert prepare_boot(slots.root, "1.0") == ("1.0", None)
    assert not (slots.root / PENDING_FILE).exists()


def test_candidate_that_keeps_exiting_is_reverted_before_systemds_start_limit(
    tmp_path: Path,
) -> None:
    slots = _slots_with_candidate(tmp_path)
    _write_pending(slots, starts=MAX_CANDIDATE_STARTS)

    assert prepare_boot(slots.root, "2.0") == ("1.0", None)
    assert slots.active_slot() == "1.0"
    assert not (slots.root / PENDING_FILE).exists()
    reverted = json.loads((slots.root / REVERTED_FILE).read_text())
    assert reverted["candidate"] == "2.0"
    assert reverted["previous"] == "1.0"
    assert reverted["reason"] == "server exited 2 times before becoming healthy"


def test_missing_previous_slot_keeps_the_candidate_without_a_check(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path)
    slots.remove_slot("1.0")

    assert prepare_boot(slots.root, "2.0") == ("2.0", None)
    assert slots.active_slot() == "2.0"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _pending() -> PendingBoot:
    return PendingBoot(candidate="2.0", previous="1.0", health_url=_HEALTH_URL, starts=1)


def test_supervisor_confirms_a_healthy_candidate(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path)
    clock = _Clock()
    answers = iter([False, False, True])

    outcome = supervise(
        slots.root,
        _pending(),
        4242,
        probe=lambda _url: next(answers),
        sleep=clock.sleep,
        clock=clock,
        kill=lambda _pid, _sig: None,
    )

    assert outcome == "confirmed"
    assert not (slots.root / PENDING_FILE).exists()
    assert slots.active_slot() == "2.0"


def test_supervisor_reverts_and_kills_a_candidate_that_never_gets_healthy(
    tmp_path: Path,
) -> None:
    slots = _slots_with_candidate(tmp_path)
    clock = _Clock()
    signals: list[tuple[int, int]] = []

    outcome = supervise(
        slots.root,
        _pending(),
        4242,
        probe=lambda _url: False,
        sleep=clock.sleep,
        clock=clock,
        kill=lambda pid, sig: signals.append((pid, sig)),
    )

    assert outcome == "reverted"
    assert clock.now >= 60.0
    assert signals[-1] == (4242, signal.SIGKILL)
    assert slots.active_slot() == "1.0"
    assert "not healthy within 60 s" in (slots.root / REVERTED_FILE).read_text()


def test_supervisor_leaves_the_decision_to_the_next_start_when_the_server_dies(
    tmp_path: Path,
) -> None:
    slots = _slots_with_candidate(tmp_path)

    def _gone(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    outcome = supervise(
        slots.root, _pending(), 4242, probe=lambda _url: False, sleep=lambda _s: None, kill=_gone
    )

    assert outcome == "server-exited"
    assert slots.active_slot() == "2.0"
    assert (slots.root / PENDING_FILE).exists()


@pytest.fixture
def health_server() -> Iterator[tuple[str, dict[str, object]]]:
    payload: dict[str, object] = {}

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/health", payload
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    ("payload", "healthy"),
    [
        ({"status": "ok", "startup_state": "ready"}, True),
        ({"status": "degraded", "startup_state": "ready", "background_task_failures": []}, True),
        ({"status": "ok", "startup_state": "starting"}, False),
        ({"status": "ok", "startup_state": "ready", "background_task_failures": ["x"]}, False),
        ({"status": "error", "startup_state": "ready"}, False),
    ],
)
def test_health_rule_matches_the_release_smoke_test(
    health_server: tuple[str, dict[str, object]],
    payload: dict[str, object],
    healthy: bool,
) -> None:
    url, served = health_server
    served.update(payload)

    assert is_healthy(url) is healthy


def test_unreachable_server_is_not_healthy() -> None:
    assert is_healthy(_HEALTH_URL) is False


_APP = '#!/bin/sh\necho "LABEL $@"\n'


def _run_service(slots: VenvSlots) -> subprocess.CompletedProcess[str]:
    """Start the server the way systemd does: through the routed ``.venv/bin``."""
    return subprocess.run(
        [str(slots.root / "bin" / "vibesensor-server"), "--config", "/etc/x.yaml"],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_launcher_runs_the_previous_slot_after_repeated_candidate_crashes(
    tmp_path: Path,
) -> None:
    slots = _slots_with_candidate(tmp_path, app_script=_APP)
    _write_pending(slots, starts=MAX_CANDIDATE_STARTS)

    result = _run_service(slots)

    assert result.stdout == "previous --config /etc/x.yaml\n"
    assert slots.active_slot() == "1.0"
    assert (slots.root / REVERTED_FILE).is_file()


def test_launcher_kills_and_reverts_a_candidate_that_stays_unhealthy(tmp_path: Path) -> None:
    slots = _slots_with_candidate(tmp_path, app_script='#!/bin/sh\necho "LABEL"\nexec sleep 20\n')
    _write_pending(slots, deadline_s=0.5)

    result = _run_service(slots)

    assert result.returncode == -signal.SIGKILL
    assert result.stdout == "candidate\n"
    assert slots.active_slot() == "1.0"
    reverted = json.loads((slots.root / REVERTED_FILE).read_text())
    assert reverted["reason"] == "not healthy within 0.5 s of starting"
