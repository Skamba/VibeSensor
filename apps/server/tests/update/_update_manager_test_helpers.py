from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibesensor.update.manager import UpdateManager
from vibesensor.update.runner import CommandRunner


class FakeRunner(CommandRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.responses: list[tuple[str, tuple[int, str, str]]] = []
        self.default_response: tuple[int, str, str] = (0, "", "")

    def set_response(self, match_substr: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((match_substr, (rc, stdout, stderr)))

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), {"timeout": timeout, "env": env}))
        joined = " ".join(args)
        for match_substr, response in self.responses:
            if match_substr in joined:
                return response
        return self.default_response


def mock_which(name: str) -> str | None:
    if name in ("nmcli", "python3"):
        return f"/usr/bin/{name}"
    return None


def seed_runtime_artifacts(repo: Path, mgr: UpdateManager, *, valid: bool = True) -> None:
    (repo / "apps" / "ui" / "src").mkdir(parents=True, exist_ok=True)
    (repo / "apps" / "server" / "vibesensor" / "static").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "tools" / "build_ui_static.py").write_text("#!/usr/bin/env python3\n")
    (repo / "apps" / "server" / "pyproject.toml").write_text("[project]\nname='vibesensor'\n")
    (repo / "apps" / "ui" / "src" / "main.ts").write_text("console.log('ui')\n")
    (repo / "apps" / "ui" / "package.json").write_text('{"name":"ui"}\n')
    (repo / "apps" / "ui" / "package-lock.json").write_text('{"name":"ui","lockfileVersion":3}\n')
    (repo / "apps" / "server" / "vibesensor" / "static" / "index.html").write_text("<html>ok</html>\n")
    details = mgr._collect_runtime_details()
    metadata = {
        "ui_source_hash": details["ui_source_hash"] if valid else "stale-source-hash",
        "static_assets_hash": details["static_assets_hash"],
        "git_commit": "deadbeef",
    }
    (repo / "apps" / "server" / "vibesensor" / "static" / ".vibesensor-ui-build.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )


async def cancel_task(mgr: UpdateManager) -> None:
    if mgr._task:
        mgr._task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await mgr._task


def assert_hotspot_restored(runner: FakeRunner) -> None:
    restore_calls = [
        call
        for call in runner.calls
        if "VibeSensor-AP" in " ".join(call[0]) and "up" in " ".join(call[0])
    ]
    assert len(restore_calls) > 0


async def run_update(
    mgr: UpdateManager,
    ssid: str = "TestNet",
    password: str = "pass123",
    *,
    timeout: float = 10,
) -> None:
    mgr.start(ssid, password)
    assert mgr._task is not None
    await asyncio.wait_for(mgr._task, timeout=timeout)


@contextmanager
def patch_release_fetcher(current_version: str = "2025.6.15") -> Iterator[MagicMock]:
    with (
        patch("shutil.which", mock_which),
        patch("vibesensor.release_fetcher.ServerReleaseFetcher") as mock_fetcher,
        patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
        patch("vibesensor._version.__version__", current_version),
    ):
        yield mock_fetcher


def setup_update_env(
    tmp_path: Path,
    *,
    sudo_ok: bool = True,
    rollback: bool = True,
    seed_artifacts: bool = False,
) -> tuple[UpdateManager, FakeRunner, Path]:
    runner = FakeRunner()
    if sudo_ok:
        runner.set_response("sudo -n true", 0)
    repo = tmp_path / "repo"
    repo.mkdir()
    kwargs: dict[str, object] = {"runner": runner, "repo_path": str(repo)}
    if rollback:
        kwargs["rollback_dir"] = str(tmp_path / "rollback")
    mgr = UpdateManager(**kwargs)
    if seed_artifacts:
        seed_runtime_artifacts(repo, mgr, valid=True)
    return mgr, runner, repo


def make_mock_release(
    version: str = "2025.6.15",
    tag: str = "server-v2025.6.15",
    sha256: str = "",
) -> MagicMock:
    release = MagicMock()
    release.version = version
    release.tag = tag
    release.sha256 = sha256
    release.asset_name = f"vibesensor-{version}-py3-none-any.whl"
    return release
