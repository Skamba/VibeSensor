from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from vibesensor.use_cases.updates.manager import UpdateManager
from vibesensor.use_cases.updates.models import UpdateTransport
from vibesensor.use_cases.updates.runner import CommandRunner
from vibesensor.use_cases.updates.runtime import build_update_manager
from vibesensor.use_cases.updates.status import UpdateStateStore, collect_runtime_details


def _build_fake_downloaded_wheel(path: Path, *, version: str) -> None:
    import zipfile

    dist_info = f"vibesensor-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: vibesensor\nVersion: {version}\n",
        )
        wheel_zip.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")


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
        if "pip" in args and "download" in args and "-d" in args:
            download_dir = Path(args[args.index("-d") + 1])
            version = next(
                (arg.split("==", 1)[1] for arg in args if arg.startswith("vibesensor==")),
                "",
            )
            if version:
                _build_fake_downloaded_wheel(
                    download_dir / f"vibesensor-{version}-py3-none-any.whl",
                    version=version,
                )
        return self.default_response


def mock_which(name: str) -> str | None:
    if name in ("nmcli", "python3"):
        return f"/usr/bin/{name}"
    return None


@contextmanager
def patch_validation_environment(
    *,
    tool_lookup: Callable[[str], str | None] = mock_which,
    effective_uid: int = 1000,
) -> Iterator[None]:
    """Patch updater validation to a deterministic non-root test environment."""

    sudo_prefix = [] if effective_uid == 0 else ["sudo", "-n"]
    with (
        patch("shutil.which", tool_lookup),
        patch("vibesensor.use_cases.updates.validation.os.geteuid", return_value=effective_uid),
        patch("vibesensor.use_cases.updates.privilege._sudo_prefix", return_value=sudo_prefix),
    ):
        yield


def seed_runtime_artifacts(repo: Path, mgr: UpdateManager, *, valid: bool = True) -> None:
    (repo / "apps" / "ui" / "src").mkdir(parents=True, exist_ok=True)
    (repo / "apps" / "server" / "vibesensor" / "static").mkdir(parents=True, exist_ok=True)
    (repo / "tools").mkdir(parents=True, exist_ok=True)
    (repo / "tools" / "build_ui_static.py").write_text("#!/usr/bin/env python3\n")
    (repo / "apps" / "server" / "pyproject.toml").write_text("[project]\nname='vibesensor'\n")
    (repo / "apps" / "ui" / "src" / "main.ts").write_text("console.log('ui')\n")
    (repo / "apps" / "ui" / "package.json").write_text('{"name":"ui"}\n')
    (repo / "apps" / "ui" / "package-lock.json").write_text('{"name":"ui","lockfileVersion":3}\n')
    (repo / "apps" / "server" / "vibesensor" / "static" / "index.html").write_text(
        "<html>ok</html>\n",
    )
    details = collect_runtime_details(repo)
    metadata = {
        "ui_source_hash": details.ui_source_hash if valid else "stale-source-hash",
        "static_assets_hash": details.static_assets_hash,
        "git_commit": "deadbeef",
    }
    (repo / "apps" / "server" / "vibesensor" / "static" / ".vibesensor-ui-build.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )


async def cancel_task(mgr: UpdateManager) -> None:
    task = mgr.job_task
    if task is not None:
        mgr.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


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
    transport: UpdateTransport = UpdateTransport.wifi,
    timeout: float = 10,
    tool_lookup: Callable[[str], str | None] = mock_which,
    effective_uid: int = 1000,
) -> None:
    with patch_validation_environment(tool_lookup=tool_lookup, effective_uid=effective_uid):
        if transport == UpdateTransport.usb_internet:
            mgr.start(transport=transport)
        else:
            mgr.start(ssid, password, transport=transport)
        task = mgr.job_task
        assert task is not None
        await asyncio.wait_for(task, timeout=timeout)


@contextmanager
def patch_release_fetcher(current_version: str = "2025.6.15") -> Iterator[MagicMock]:
    with (
        patch_validation_environment(),
        patch("vibesensor.__version__", current_version),
    ):
        mock_fetcher = MagicMock()
        mock_fetcher.find_latest_release.return_value = make_mock_release(
            version=current_version,
            tag=f"server-v{current_version}",
        )
        yield mock_fetcher


def setup_update_env(
    tmp_path: Path,
    *,
    sudo_ok: bool = True,
    rollback: bool = True,
    seed_artifacts: bool = False,
    usb_internet_service: object | None = None,
    server_release_fetcher: object | None = None,
) -> tuple[UpdateManager, FakeRunner, Path]:
    runner = FakeRunner()
    if sudo_ok:
        runner.set_response("python3 -c pass", 0)
    repo = tmp_path / "repo"
    repo.mkdir()
    kwargs: dict[str, object] = {
        "runner": runner,
        "repo_path": str(repo),
        "state_store": UpdateStateStore(tmp_path / "update_status.json"),
    }
    if rollback:
        kwargs["rollback_dir"] = str(tmp_path / "rollback")
    if usb_internet_service is not None:
        kwargs["usb_internet_service"] = usb_internet_service
    if server_release_fetcher is not None:
        kwargs["server_release_fetcher"] = server_release_fetcher
    mgr = build_update_manager(**kwargs)
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
