from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import tarfile
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_support.venv_slots import make_legacy_venv, simulate_slot_command

from vibesensor.updates.manager import UpdateManager
from vibesensor.updates.models import UpdateTransport
from vibesensor.updates.runner import CommandRunner
from vibesensor.updates.runtime import build_update_manager
from vibesensor.updates.status.payload_codec import UpdateStateStore
from vibesensor.updates.status.runtime_details import collect_runtime_details


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
        self.response_sequences: list[tuple[str, deque[tuple[int, str, str]]]] = []
        self.default_response: tuple[int, str, str] = (0, "", "")

    def set_response(self, match_substr: str, rc: int, stdout: str = "", stderr: str = "") -> None:
        self.responses.append((match_substr, (rc, stdout, stderr)))

    def set_response_sequence(
        self,
        match_substr: str,
        *responses: tuple[int, str, str],
    ) -> None:
        self.response_sequences.append((match_substr, deque(responses)))

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
        privileged: bool = False,
    ) -> tuple[int, str, str]:
        self.calls.append((list(args), {"timeout": timeout, "env": env, "privileged": privileged}))
        joined = " ".join(args)
        for match_substr, response_queue in self.response_sequences:
            if match_substr in joined and response_queue:
                return response_queue.popleft()
        for match_substr, response in self.responses:
            if match_substr in joined:
                return response
        simulate_slot_command(args)
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

    with (
        patch("shutil.which", tool_lookup),
        patch("vibesensor.updates.validation.os.geteuid", return_value=effective_uid),
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
    privileged_ok: bool = True,
    seed_artifacts: bool = False,
    usb_internet_service: object | None = None,
    server_release_fetcher: object | None = None,
) -> tuple[UpdateManager, FakeRunner, Path]:
    runner = FakeRunner()
    if privileged_ok:
        runner.set_response("python3 -c pass", 0)
    repo = tmp_path / "repo"
    make_legacy_venv(repo / "apps" / "server" / ".venv")
    kwargs: dict[str, object] = {
        "runner": runner,
        "repo_path": str(repo),
        "state_store": UpdateStateStore(tmp_path / "update_status.json"),
    }
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


def publish_release(
    fetcher: MagicMock,
    assets_dir: Path,
    *,
    version: str = "2025.6.15",
    wheel_sha256: str | None = None,
) -> MagicMock:
    """Make *fetcher* serve a release whose wheel and wheelhouse download like GitHub assets."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    wheel = assets_dir / f"vibesensor-{version}-py3-none-any.whl"
    _build_fake_downloaded_wheel(wheel, version=version)
    dependency = assets_dir / "anyio-4.15.1-py3-none-any.whl"
    dependency.write_bytes(b"dependency")
    wheelhouse = assets_dir / f"vibesensor-wheelhouse-{version}-cp313-linux_armv7l.tar"
    with tarfile.open(wheelhouse, "w") as tar:
        tar.add(dependency, arcname=dependency.name)

    release = make_mock_release(
        version=version,
        tag=f"server-v{version}",
        sha256=wheel_sha256 or hashlib.sha256(wheel.read_bytes()).hexdigest(),
    )
    release.asset_url = "https://api.github.com/assets/wheel"
    release.wheelhouse_name = wheelhouse.name
    release.wheelhouse_url = "https://api.github.com/assets/wheelhouse"
    release.wheelhouse_sha256 = hashlib.sha256(wheelhouse.read_bytes()).hexdigest()
    sources = {release.asset_url: wheel, release.wheelhouse_url: wheelhouse}

    def _download(name: str, url: str, dest_dir: Path) -> Path:
        dest = Path(dest_dir) / name
        shutil.copyfile(sources[url], dest)
        return dest

    fetcher.download_asset.side_effect = _download
    fetcher.find_latest_release.return_value = release
    return release
