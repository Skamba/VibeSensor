"""Guard the Docker dev workflow entrypoints and UI dependency caching."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tests._paths import REPO_ROOT

_MAKEFILE = REPO_ROOT / "Makefile"
_DOCKER_DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
_UI_KNIP_CONFIG = REPO_ROOT / "apps" / "ui" / "knip.jsonc"
_UI_PACKAGE_JSON = REPO_ROOT / "apps" / "ui" / "package.json"
_UI_DEV_SCRIPT = REPO_ROOT / "apps" / "ui" / "dev-docker.sh"
_UI_README = REPO_ROOT / "apps" / "ui" / "README.md"


def _package_scripts() -> dict[str, str]:
    package_json = json.loads(_UI_PACKAGE_JSON.read_text(encoding="utf-8"))
    return {str(name): str(command) for name, command in package_json["scripts"].items()}


def _docker_dev_config() -> dict[str, object]:
    loaded = yaml.safe_load(_DOCKER_DEV_COMPOSE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


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


def test_make_dev_target_wraps_docker_dev_compose() -> None:
    makefile_text = _MAKEFILE.read_text(encoding="utf-8")

    assert (
        "dev: ## Start the source-mounted Docker dev stack with backend reload + Vite HMR"
        in makefile_text
    )
    assert (
        "docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build" in makefile_text
    )


def test_makefile_exposes_ui_unit_test_target_and_readme_pointer() -> None:
    makefile_text = _MAKEFILE.read_text(encoding="utf-8")
    readme_text = _UI_README.read_text(encoding="utf-8")

    assert "ui-test: ## Run UI unit tests" in makefile_text
    assert 'cd $(UI_DIR) && PYTHON="$$PYTHON" npm run test:unit' in makefile_text
    assert "make ui-test                 # same unit suite from the repo root" in readme_text


def test_ui_knip_exports_scope_and_readme_pointer() -> None:
    scripts = _package_scripts()
    knip_text = _UI_KNIP_CONFIG.read_text(encoding="utf-8")
    readme_text = _UI_README.read_text(encoding="utf-8")

    assert scripts["lint:unused"] == "knip --config knip.jsonc"
    assert '"include": ["files", "dependencies", "exports"]' in knip_text
    assert "npm run lint:unused  # knip dead-file/dependency/export checks" in readme_text
    assert "cleaned-up unused" in readme_text
    assert "Exported-type checks still stay out" in readme_text


def test_ui_format_check_is_wired_to_local_and_ci_quality() -> None:
    scripts = _package_scripts()
    makefile_text = _MAKEFILE.read_text(encoding="utf-8")
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    readme_text = _UI_README.read_text(encoding="utf-8")

    assert scripts["format:check"] == "biome check . --linter-enabled=false --assist-enabled=false"
    assert "npm run format:check" in makefile_text
    assert "npm run format:check" in workflow_text
    assert "npm run format:check # Biome formatter drift check" in readme_text


def test_docker_dev_ui_service_uses_guarded_dev_script_and_healthcheck() -> None:
    scripts = _package_scripts()
    compose = _docker_dev_config()
    services = compose["services"]
    assert isinstance(services, dict)
    ui_service = services["vibesensor-ui-dev"]
    assert isinstance(ui_service, dict)

    assert scripts["dev:docker"] == "sh ./dev-docker.sh"
    assert ui_service["command"] == [
        "npm",
        "run",
        "dev:docker",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5173",
    ]

    healthcheck = ui_service["healthcheck"]
    assert isinstance(healthcheck, dict)
    test_command = healthcheck["test"]
    assert test_command[:3] == ["CMD", "node", "-e"]
    assert "127.0.0.1:5173/" in test_command[3]
    assert healthcheck["start_period"] == "75s"


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
