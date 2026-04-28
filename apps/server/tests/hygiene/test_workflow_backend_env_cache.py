"""Guard the shared backend CI setup action's installed-environment cache contract."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._paths import REPO_ROOT

_SETUP_BACKEND = REPO_ROOT / ".github" / "actions" / "setup-backend" / "action.yml"


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"Expected YAML mapping in {path}"
    return loaded


def test_setup_backend_caches_repo_virtualenv_with_explicit_invalidation_inputs() -> None:
    setup_backend = _load_yaml(_SETUP_BACKEND)

    outputs = setup_backend["outputs"]
    assert isinstance(outputs, dict)
    assert outputs["python-path"]["value"] == "${{ steps.backend-python.outputs.python-path }}"

    steps = setup_backend["runs"]["steps"]
    assert isinstance(steps, list)

    cache_step = next(
        step for step in steps if isinstance(step, dict) and step.get("id") == "backend-venv-cache"
    )
    assert cache_step["uses"] == "actions/cache@v5"
    cache_with = cache_step["with"]
    assert isinstance(cache_with, dict)
    assert cache_with["path"] == ".venv"
    cache_key = cache_with["key"]
    assert isinstance(cache_key, str)
    assert "backend-venv" in cache_key
    assert "runner.os" in cache_key
    assert "runner.arch" in cache_key
    assert ".python-version" in cache_key
    assert "apps/server/pyproject.toml" in cache_key
    assert ".github/actions/setup-python/action.yml" in cache_key
    assert ".github/actions/setup-backend/action.yml" in cache_key
    assert "restore-keys" not in cache_with

    hit_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Report backend virtualenv cache hit"
    )
    assert hit_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit == 'true' }}"

    miss_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Report backend virtualenv cache miss"
    )
    assert miss_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}"

    install_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Install dependencies"
    )
    assert install_step["if"] == "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}"
    install_run = install_step["run"]
    assert isinstance(install_run, str)
    assert "rm -rf .venv" in install_run
    assert '"${{ steps.setup-python.outputs.python-path }}" -m venv .venv' in install_run
    assert ".venv/bin/python -m pip install --upgrade pip" in install_run
    assert '.venv/bin/python -m pip install -e "./apps/server[dev]"' in install_run

    backend_python_step = next(
        step for step in steps if isinstance(step, dict) and step.get("id") == "backend-python"
    )
    backend_python_run = backend_python_step["run"]
    assert isinstance(backend_python_run, str)
    assert 'echo "${GITHUB_WORKSPACE}/.venv/bin" >> "${GITHUB_PATH}"' in backend_python_run
    assert 'echo "VIRTUAL_ENV=${GITHUB_WORKSPACE}/.venv" >> "${GITHUB_ENV}"' in backend_python_run
    assert 'echo "python-path=${backend_python}" >> "${GITHUB_OUTPUT}"' in backend_python_run

    platformio_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Install PlatformIO dependencies"
    )
    platformio_run = platformio_step["run"]
    assert isinstance(platformio_run, str)
    assert (
        'retry_command 3 "${{ steps.backend-python.outputs.python-path }}"'
        ' -m pip install "platformio>=6,<7"' in platformio_run
    )
