"""Behaviour of the periodic hotspot watchdog against a scripted nmcli/systemctl."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from vibesensor.cli.hotspot_self_heal import main
from vibesensor.hotspot.constants import HOTSPOT_CON_NAME, HOTSPOT_PROVISION_UNIT
from vibesensor.hotspot.watchdog import RETRY_DELAYS_S, check_hotspot, run_command

_ACTIVE = ("nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active")
_UP = ("nmcli", "--wait", "15", "connection", "up", HOTSPOT_CON_NAME)
_REPROVISION = ("systemctl", "restart", "--no-block", HOTSPOT_PROVISION_UNIT)


class FakeSystem:
    """Answers commands from a script; each argv maps to a queue of (rc, stdout)."""

    def __init__(self, script: dict[tuple[str, ...], list[tuple[int, str]]]) -> None:
        self._script = script
        self.calls: list[tuple[str, ...]] = []
        self.sleeps: list[float] = []

    def run(self, argv: Sequence[str], timeout_s: float) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append(key)
        queue = self._script[key]
        rc, stdout = queue.pop(0) if len(queue) > 1 else queue[0]
        return subprocess.CompletedProcess(list(argv), rc, stdout, "boom" if rc else "")

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _check(fake: FakeSystem) -> int:
    return check_hotspot(fake.run, fake.sleep)


def test_active_hotspot_is_left_alone() -> None:
    fake = FakeSystem({_ACTIVE: [(0, f"{HOTSPOT_CON_NAME}:wlan0\nlo:lo\n")]})

    assert _check(fake) == 0
    assert fake.calls == [_ACTIVE]


def test_interface_owned_by_update_uplink_is_left_alone() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "VibeSensor-Uplink:wlan0\n")]})

    assert _check(fake) == 0
    assert fake.calls == [_ACTIVE]


def test_inactive_hotspot_is_brought_up_after_backoff() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "eth0-wired:eth0\n")], _UP: [(10, ""), (0, "")]})

    assert _check(fake) == 0
    assert fake.calls == [_ACTIVE, _UP, _UP]
    assert fake.sleeps == [RETRY_DELAYS_S[1]]


def test_persistent_up_failure_reprovisions_the_hotspot() -> None:
    fake = FakeSystem({_ACTIVE: [(0, "")], _UP: [(10, "")], _REPROVISION: [(0, "")]})

    assert _check(fake) == 1
    assert fake.calls == [_ACTIVE, *[_UP] * len(RETRY_DELAYS_S), _REPROVISION]
    assert fake.sleeps == [delay for delay in RETRY_DELAYS_S if delay]


@pytest.mark.parametrize(("restart_rc", "expected"), [(0, 1), (1, 2)])
def test_unresponsive_networkmanager_reprovisions(restart_rc: int, expected: int) -> None:
    fake = FakeSystem({_ACTIVE: [(8, "")], _REPROVISION: [(restart_rc, "")]})

    assert _check(fake) == expected
    assert fake.calls == [_ACTIVE, _REPROVISION]


def test_run_command_reports_missing_binary_as_failure() -> None:
    result = run_command(["/nonexistent/vibesensor-binary"], 1)

    assert result.returncode == 127


def test_cli_ignores_legacy_unit_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["vibesensor-hotspot-self-heal", "--mode", "check-heal", "--config", "/etc/x.yaml"],
    )
    monkeypatch.setattr("vibesensor.cli.hotspot_self_heal.check_hotspot", lambda: 0)

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
