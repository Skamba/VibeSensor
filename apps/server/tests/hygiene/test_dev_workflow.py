"""Guard the Docker dev workflow entrypoints and UI dependency caching."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_UI_DEV_SCRIPT = REPO_ROOT / "apps" / "ui" / "dev-docker.sh"


def _write_fake_npm(bin_dir: Path) -> None:
    fake_npm = bin_dir / "npm"
    fake_npm.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "from pathlib import Path",
                "import os",
                "import sys",
                "",
                "log_path = Path(os.environ['FAKE_NPM_LOG'])",
                "with log_path.open('a', encoding='utf-8') as handle:",
                "    handle.write(' '.join(sys.argv[1:]) + '\\n')",
                "if sys.argv[1:3] == ['run', 'sync:generated-contracts'] and "
                "os.environ.get('FAKE_CONTRACTS_FAIL') == '1':",
                "    sys.exit(17)",
                "sys.exit(0)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)


def _prepare_ui_workspace(
    tmp_path: Path,
    *,
    create_node_modules: bool,
    stored_lock_hash: str | None,
) -> tuple[Path, Path]:
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    package_lock = ui_dir / "package-lock.json"
    package_lock.write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    if create_node_modules:
        (ui_dir / "node_modules").mkdir()
    if stored_lock_hash is not None:
        (ui_dir / ".npm-ci-lock.sha256").write_text(f"{stored_lock_hash}\n", encoding="utf-8")
    return ui_dir, package_lock


def _run_dev_docker_script(
    ui_dir: Path, tmp_path: Path, *, fail_contracts: bool = False
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_npm(bin_dir)
    log_path = tmp_path / "npm.log"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_NPM_LOG": str(log_path),
    }
    if fail_contracts:
        env["FAKE_CONTRACTS_FAIL"] = "1"
    result = subprocess.run(
        ["sh", str(_UI_DEV_SCRIPT), "--host", "0.0.0.0", "--port", "5173"],
        cwd=ui_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    commands = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    return result, commands


def test_dev_docker_runs_npm_ci_and_marks_lock_hash_when_node_modules_missing(
    tmp_path: Path,
) -> None:
    ui_dir, package_lock = _prepare_ui_workspace(
        tmp_path,
        create_node_modules=False,
        stored_lock_hash=None,
    )

    result, commands = _run_dev_docker_script(ui_dir, tmp_path)

    assert result.returncode == 0
    assert commands == [
        "ci",
        "run sync:generated-contracts",
        "run dev -- --host 0.0.0.0 --port 5173",
    ]
    assert (ui_dir / ".npm-ci-lock.sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(
        package_lock.read_bytes()
    ).hexdigest()


def test_dev_docker_reinstalls_when_lock_hash_is_stale(tmp_path: Path) -> None:
    ui_dir, package_lock = _prepare_ui_workspace(
        tmp_path,
        create_node_modules=True,
        stored_lock_hash="stale-hash",
    )

    result, commands = _run_dev_docker_script(ui_dir, tmp_path)

    assert result.returncode == 0
    assert commands == [
        "ci",
        "run sync:generated-contracts",
        "run dev -- --host 0.0.0.0 --port 5173",
    ]
    assert (ui_dir / ".npm-ci-lock.sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(
        package_lock.read_bytes()
    ).hexdigest()


def test_dev_docker_skips_npm_ci_when_lock_hash_is_current(tmp_path: Path) -> None:
    ui_dir, package_lock = _prepare_ui_workspace(
        tmp_path,
        create_node_modules=True,
        stored_lock_hash=hashlib.sha256(b'{"lockfileVersion": 3}\n').hexdigest(),
    )
    assert (
        hashlib.sha256(package_lock.read_bytes()).hexdigest()
        == hashlib.sha256(b'{"lockfileVersion": 3}\n').hexdigest()
    )

    result, commands = _run_dev_docker_script(ui_dir, tmp_path)

    assert result.returncode == 0
    assert commands == [
        "run sync:generated-contracts",
        "run dev -- --host 0.0.0.0 --port 5173",
    ]


def test_dev_docker_fails_fast_when_contract_regeneration_fails(tmp_path: Path) -> None:
    ui_dir, package_lock = _prepare_ui_workspace(
        tmp_path,
        create_node_modules=True,
        stored_lock_hash=hashlib.sha256(b'{"lockfileVersion": 3}\n').hexdigest(),
    )
    assert (ui_dir / ".npm-ci-lock.sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(
        package_lock.read_bytes()
    ).hexdigest()

    result, commands = _run_dev_docker_script(ui_dir, tmp_path, fail_contracts=True)

    assert result.returncode == 17
    assert commands == ["run sync:generated-contracts"]
    assert "make sync-contracts" in result.stderr
