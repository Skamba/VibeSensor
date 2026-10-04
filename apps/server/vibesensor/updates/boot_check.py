"""Boot check for A/B venv slots: run, confirm, or revert a freshly installed release.

The updater copies this file into every slot as ``<slot>/bin/vibesensor-server``
(next to the real console script, renamed ``vibesensor-server.app``). systemd
starts it through ``.venv/bin -> current/bin``, so it always runs as the active
slot. The copy comes from the release that *installed* the slot, so a broken
candidate never judges itself. It must stay stdlib-only and runs as
``python -IS``.

While ``boot-pending.json`` names the active slot as the candidate:

- each start increments ``starts``; on start number ``MAX_CANDIDATE_STARTS + 1``
  (the candidate kept crashing) it flips ``current`` back to ``previous`` and
  runs that slot instead,
- a detached supervisor polls the health URL; when the server works (see
  :func:`not_working_reason`: started, no failed startup task, database intact,
  processing loop running; sensor and device warnings do not count) it deletes
  the marker (confirmed), and when ``deadline_s`` passes first it flips
  back, records ``boot-reverted.json``, and SIGKILLs the server so systemd
  (``Restart=on-failure``) restarts into the previous slot.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

PENDING_FILE = "boot-pending.json"
REVERTED_FILE = "boot-reverted.json"
CURRENT_LINK = "current"
SLOTS_DIR = "slots"
SERVER_APP = "vibesensor-server.app"
MAX_CANDIDATE_STARTS = 2
HEALTH_DEADLINE_S = 60.0
_POLL_INTERVAL_S = 2.0


@dataclass(frozen=True)
class PendingBoot:
    """A switched-to candidate slot that has not yet proven it boots healthy."""

    candidate: str
    previous: str
    health_url: str
    starts: int = 0
    deadline_s: float = HEALTH_DEADLINE_S


def _log(message: str) -> None:
    print(f"boot-check: {message}", file=sys.stderr, flush=True)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    """Durably replace *path* with *payload* (temp file, fsync, rename)."""
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def switch_current(root: Path, slot: str) -> None:
    """Atomically point ``<root>/current`` at ``slots/<slot>``."""
    tmp = root / f".{CURRENT_LINK}.tmp"
    tmp.unlink(missing_ok=True)
    os.symlink(f"{SLOTS_DIR}/{slot}", tmp)
    os.replace(tmp, root / CURRENT_LINK)
    _fsync_dir(root)


def read_pending(root: Path) -> PendingBoot | None:
    try:
        data = json.loads((root / PENDING_FILE).read_text(encoding="utf-8"))
        pending = PendingBoot(**data)
    except (OSError, ValueError, TypeError):
        return None
    if not (isinstance(pending.candidate, str) and isinstance(pending.previous, str)):
        return None
    return pending


def revert(root: Path, pending: PendingBoot, reason: str) -> None:
    """Make ``previous`` active again and record why the candidate was rejected."""
    switch_current(root, pending.previous)
    write_json_atomic(
        root / REVERTED_FILE,
        {
            "candidate": pending.candidate,
            "previous": pending.previous,
            "reason": reason,
            "at": time.time(),
        },
    )
    (root / PENDING_FILE).unlink(missing_ok=True)
    _log(f"reverted {pending.candidate} -> {pending.previous}: {reason}")


def prepare_boot(root: Path, slot: str) -> tuple[str, PendingBoot | None]:
    """Return the slot to run and, when it is an unconfirmed candidate, its marker."""
    pending = read_pending(root)
    if pending is None:
        return slot, None
    if pending.candidate != slot:
        # The switch to the candidate never happened or was already undone.
        (root / PENDING_FILE).unlink(missing_ok=True)
        return slot, None
    if not (root / SLOTS_DIR / pending.previous / "bin" / SERVER_APP).is_file():
        _log(f"previous slot {pending.previous} is missing; keeping {slot} without a check")
        (root / PENDING_FILE).unlink(missing_ok=True)
        return slot, None
    if pending.starts >= MAX_CANDIDATE_STARTS:
        revert(root, pending, f"server exited {pending.starts} times before becoming healthy")
        return pending.previous, None
    started = PendingBoot(**{**asdict(pending), "starts": pending.starts + 1})
    write_json_atomic(root / PENDING_FILE, asdict(started))
    _log(f"starting candidate {slot} (start {started.starts}/{MAX_CANDIDATE_STARTS})")
    return slot, started


def not_working_reason(payload: object) -> str | None:
    """Why an ``/api/health`` payload shows a server that does not work yet, or None.

    Judges only the new version itself: it finished starting, no startup task
    failed, its database is intact, and its processing loop runs. It ignores
    the overall ``status``, because ``warn`` and ``degraded`` also cover sensors
    and the device (dropped frames, no GPS receiver, a sensor still to be
    flashed, an outdated root side), and going back to the previous version
    fixes none of those. A field missing from the payload counts as fine, so a
    later release can drop one without being reverted. The release smoke test
    (``releases/release_validation.py``) uses the same rule.
    """

    if not isinstance(payload, dict):
        return "the health response is not a JSON object"
    if payload.get("startup_state") != "ready":
        return f"startup_state is {payload.get('startup_state')!r}"
    if payload.get("startup_error"):
        return f"startup failed: {payload['startup_error']}"
    if payload.get("background_task_failures"):
        return f"startup tasks failed: {payload['background_task_failures']}"
    if payload.get("db_corruption_detected"):
        return "the history database is corrupt"
    if payload.get("processing_state", "ok") != "ok":
        return f"the processing loop is {payload['processing_state']}"
    return None


def is_healthy(url: str) -> bool:
    """True when the server at *url* answers and :func:`not_working_reason` finds nothing."""
    try:
        with urlopen(url, timeout=3.0) as response:
            payload = json.load(response)
    except (OSError, ValueError):
        return False
    return not_working_reason(payload) is None


def _alive(pid: int, kill: Callable[[int, int], None]) -> bool:
    try:
        kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def supervise(
    root: Path,
    pending: PendingBoot,
    server_pid: int,
    *,
    probe: Callable[[str], bool] = is_healthy,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    kill: Callable[[int, int], None] = os.kill,
) -> str:
    """Confirm the candidate once healthy, or revert it at the deadline."""
    deadline = clock() + pending.deadline_s
    while clock() < deadline:
        if not _alive(server_pid, kill):
            return "server-exited"  # systemd restarts it; the next start decides.
        if probe(pending.health_url):
            (root / PENDING_FILE).unlink(missing_ok=True)
            _log(f"candidate {pending.candidate} is healthy; update confirmed")
            return "confirmed"
        sleep(_POLL_INTERVAL_S)
    revert(root, pending, f"not healthy within {pending.deadline_s:g} s of starting")
    kill(server_pid, signal.SIGKILL)
    return "reverted"


def _spawn_supervisor(root: Path, pending: PendingBoot) -> None:
    server_pid = os.getpid()
    child = os.fork()
    if child:
        os.waitpid(child, 0)
        return
    if os.fork():
        os._exit(0)
    try:
        supervise(root, pending, server_pid)
    except Exception as exc:  # last resort: nothing above this detached process logs it
        _log(f"supervisor failed: {exc!r}")
    finally:
        os._exit(0)


def main() -> None:
    slot_dir = Path(__file__).resolve().parent.parent
    root = slot_dir.parent.parent
    run_slot, pending = prepare_boot(root, slot_dir.name)
    if pending is not None:
        _spawn_supervisor(root, pending)
    app = root / SLOTS_DIR / run_slot / "bin" / SERVER_APP
    os.execv(app, [str(app), *sys.argv[1:]])


if __name__ == "__main__":
    main()
