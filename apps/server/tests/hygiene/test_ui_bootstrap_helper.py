"""Guard the shared UI bootstrap helper behavior."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_UI_BOOTSTRAP_HELPER = REPO_ROOT / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
_GENERATED_DERIVATIVE_RELATIVE_PATHS = (
    "src/generated/http_api_contracts.ts",
    "src/contracts/ws_payload_types.ts",
    "src/contracts/ws_payload_schema.generated.ts",
    "src/constants.ts",
)


def _write_fake_npm(bin_dir: Path) -> Path:
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
                "if sys.argv[1:] == ['ci']:",
                "    Path('node_modules').mkdir(exist_ok=True)",
                "sys.exit(0)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    return fake_npm


def _prepare_ui_dir(tmp_path: Path) -> Path:
    ui_dir = tmp_path / "ui"
    ui_dir.mkdir()
    (ui_dir / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    return ui_dir


def _mark_npm_ci_current(ui_dir: Path) -> None:
    (ui_dir / "node_modules").mkdir()
    lock_hash = hashlib.sha256((ui_dir / "package-lock.json").read_bytes()).hexdigest()
    (ui_dir / ".npm-ci-lock.sha256").write_text(f"{lock_hash}\n", encoding="utf-8")


def _write_generated_derivatives(ui_dir: Path) -> None:
    for rel_path in _GENERATED_DERIVATIVE_RELATIVE_PATHS:
        file_path = ui_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("// generated\n", encoding="utf-8")


def test_ui_bootstrap_helper_runs_npm_ci_and_marks_lock_hash(tmp_path: Path) -> None:
    ui_dir = _prepare_ui_dir(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_npm(bin_dir)
    log_path = tmp_path / "npm.log"

    result = subprocess.run(
        ["node", str(_UI_BOOTSTRAP_HELPER), "--log-prefix", "[test]"],
        cwd=ui_dir,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_NPM_LOG": str(log_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == ["ci"]
    assert (ui_dir / ".npm-ci-lock.sha256").read_text(encoding="utf-8").strip() == hashlib.sha256(
        (ui_dir / "package-lock.json").read_bytes()
    ).hexdigest()


def test_ui_bootstrap_helper_skips_npm_ci_when_lock_hash_is_current(tmp_path: Path) -> None:
    ui_dir = _prepare_ui_dir(tmp_path)
    (ui_dir / "node_modules").mkdir()
    lock_hash = hashlib.sha256((ui_dir / "package-lock.json").read_bytes()).hexdigest()
    (ui_dir / ".npm-ci-lock.sha256").write_text(f"{lock_hash}\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_npm(bin_dir)
    log_path = tmp_path / "npm.log"

    result = subprocess.run(
        ["node", str(_UI_BOOTSTRAP_HELPER)],
        cwd=ui_dir,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_NPM_LOG": str(log_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert not log_path.exists()
    assert (
        "[ui:bootstrap] Skipping npm ci because node_modules and package-lock marker are current."
        in result.stdout
    )


def test_ui_bootstrap_helper_check_mode_reports_npm_ci_need(tmp_path: Path) -> None:
    ui_dir = _prepare_ui_dir(tmp_path)

    result = subprocess.run(
        ["node", str(_UI_BOOTSTRAP_HELPER), "--check"],
        cwd=ui_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "needs_npm_ci": True,
        "lock_hash": hashlib.sha256((ui_dir / "package-lock.json").read_bytes()).hexdigest(),
        "current_lock_hash": "",
        "node_modules_exists": False,
    }


def test_ui_bootstrap_helper_materializes_missing_generated_contracts_when_requested(
    tmp_path: Path,
) -> None:
    ui_dir = _prepare_ui_dir(tmp_path)
    _mark_npm_ci_current(ui_dir)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_npm(bin_dir)
    log_path = tmp_path / "npm.log"

    result = subprocess.run(
        ["node", str(_UI_BOOTSTRAP_HELPER), "--ensure-generated-contracts"],
        cwd=ui_dir,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_NPM_LOG": str(log_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == ["run sync:generated-contracts"]


def test_ui_bootstrap_helper_skips_generated_contract_sync_when_derivatives_exist(
    tmp_path: Path,
) -> None:
    ui_dir = _prepare_ui_dir(tmp_path)
    _mark_npm_ci_current(ui_dir)
    _write_generated_derivatives(ui_dir)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_npm(bin_dir)
    log_path = tmp_path / "npm.log"

    result = subprocess.run(
        ["node", str(_UI_BOOTSTRAP_HELPER), "--ensure-generated-contracts"],
        cwd=ui_dir,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_NPM_LOG": str(log_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert not log_path.exists()
