"""Guard the shared backend CI setup action's cache and interpreter contracts."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._paths import REPO_ROOT

_SETUP_BACKEND = REPO_ROOT / ".github" / "actions" / "setup-backend" / "action.yml"


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"Expected YAML mapping in {path}"
    return loaded


def _action_steps() -> list[dict[str, object]]:
    setup_backend = _load_yaml(_SETUP_BACKEND)
    steps = setup_backend["runs"]["steps"]
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _named_step(steps: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(step for step in steps if step.get("name") == name)


def _step_by_id(steps: list[dict[str, object]], step_id: str) -> dict[str, object]:
    return next(step for step in steps if step.get("id") == step_id)


def test_setup_backend_exports_repo_virtualenv_python_path() -> None:
    setup_backend = _load_yaml(_SETUP_BACKEND)

    outputs = setup_backend["outputs"]
    assert isinstance(outputs, dict)
    assert outputs["python-path"]["value"] == "${{ steps.backend-python.outputs.python-path }}"

    backend_python_run = _step_by_id(_action_steps(), "backend-python")["run"]
    assert isinstance(backend_python_run, str)
    assert "${GITHUB_WORKSPACE}/.venv/bin/python" in backend_python_run
    assert "GITHUB_PATH" in backend_python_run
    assert "VIRTUAL_ENV=${GITHUB_WORKSPACE}/.venv" in backend_python_run
    assert "python-path=${backend_python}" in backend_python_run


def test_setup_backend_cache_has_explicit_repo_invalidation_without_restore_keys() -> None:
    steps = _action_steps()
    cache_step = _step_by_id(steps, "backend-venv-cache")

    assert cache_step["uses"] == "actions/cache@v5"
    cache_with = cache_step["with"]
    assert isinstance(cache_with, dict)
    assert cache_with["path"] == ".venv"
    assert "restore-keys" not in cache_with

    cache_key = cache_with["key"]
    assert isinstance(cache_key, str)
    assert "backend-venv" in cache_key
    assert "runner.os" in cache_key
    assert "runner.arch" in cache_key
    for path in (
        ".python-version",
        "apps/server/pyproject.toml",
        ".github/actions/setup-python/action.yml",
        ".github/actions/setup-backend/action.yml",
    ):
        assert path in cache_key
        assert (REPO_ROOT / path).exists()

    hit_step = _named_step(steps, "Report backend virtualenv cache hit")
    assert hit_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit == 'true' }}"
    miss_step = _named_step(steps, "Report backend virtualenv cache miss")
    assert miss_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}"


def test_setup_backend_rebuilds_cache_misses_with_retry_helper() -> None:
    steps = _action_steps()

    prepare_retry_run = _named_step(steps, "Prepare retry helper")["run"]
    assert isinstance(prepare_retry_run, str)
    assert prepare_retry_run.count("retry_command()") == 1

    install_step = _named_step(steps, "Install dependencies")
    assert install_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}"
    install_run = install_step["run"]
    assert isinstance(install_run, str)
    assert 'source "${RUNNER_TEMP}/setup-backend-retry.sh"' in install_run
    assert '.venv/bin/python -m pip install -e "./apps/server[dev]"' in install_run
    assert install_run.index("rm -rf .venv") < install_run.index("pip install -e")
    assert "retry_command()" not in install_run


def test_setup_backend_platformio_install_is_opt_in_and_uses_configured_python() -> None:
    platformio_step = _named_step(_action_steps(), "Install PlatformIO dependencies")
    assert platformio_step["if"] == "${{ inputs.include-platformio == 'true' }}"

    platformio_run = platformio_step["run"]
    assert isinstance(platformio_run, str)
    assert 'source "${RUNNER_TEMP}/setup-backend-retry.sh"' in platformio_run
    assert (
        'retry_command 3 "${{ steps.backend-python.outputs.python-path }}"'
        ' -m pip install "platformio>=6,<7"' in platformio_run
    )
