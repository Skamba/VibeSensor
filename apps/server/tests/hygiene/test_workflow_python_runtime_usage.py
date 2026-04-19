"""Guard GitHub Actions Python commands against ambient interpreter drift."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._paths import REPO_ROOT

_SETUP_PYTHON = REPO_ROOT / ".github" / "actions" / "setup-python" / "action.yml"
_SETUP_BACKEND = REPO_ROOT / ".github" / "actions" / "setup-backend" / "action.yml"
_BUILD_PI_IMAGE = REPO_ROOT / ".github" / "actions" / "build-pi-image" / "action.yml"
_MAIN_RELEASE = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
_WEEKLY_PI_IMAGE = REPO_ROOT / ".github" / "workflows" / "weekly-pi-image.yml"
_MANUAL_PI_IMAGE = REPO_ROOT / ".github" / "workflows" / "manual-pi-image-arm.yml"
_CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_APP_ARTIFACTS = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "app_artifacts.sh"
_PI_GEN_REPO = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "pi_gen_repo.sh"
_PREREQS = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "prereqs.sh"


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"Expected YAML mapping in {path}"
    return loaded


def test_setup_actions_expose_configured_python_path() -> None:
    setup_python = _load_yaml(_SETUP_PYTHON)
    outputs = setup_python["outputs"]
    assert isinstance(outputs, dict)
    assert outputs["python-path"]["value"] == ("${{ steps.setup-python.outputs.python-path }}")
    steps = setup_python["runs"]["steps"]
    assert steps[0]["id"] == "setup-python"
    assert steps[0]["uses"] == "actions/setup-python@v6"

    setup_backend = _load_yaml(_SETUP_BACKEND)
    backend_outputs = setup_backend["outputs"]
    assert isinstance(backend_outputs, dict)
    assert backend_outputs["python-path"]["value"] == (
        "${{ steps.setup-python.outputs.python-path }}"
    )
    backend_steps = setup_backend["runs"]["steps"]
    assert backend_steps[0]["id"] == "setup-python"
    assert backend_steps[0]["uses"] == "./.github/actions/setup-python"


def test_workflows_use_configured_python_runtime_paths() -> None:
    for workflow_path in (_MAIN_RELEASE, _WEEKLY_PI_IMAGE, _MANUAL_PI_IMAGE, _CI):
        text = workflow_path.read_text(encoding="utf-8")
        assert "python3 " not in text, f"{workflow_path} still hardcodes ambient python3"

    main_release = _load_yaml(_MAIN_RELEASE)
    release_steps = main_release["jobs"]["release"]["steps"]
    assert isinstance(release_steps, list)
    setup_index = next(
        i
        for i, step in enumerate(release_steps)
        if isinstance(step, dict) and step.get("id") == "setup-python"
    )
    build_ui_index = next(
        i
        for i, step in enumerate(release_steps)
        if isinstance(step, dict) and step.get("name") == "Build UI"
    )
    compute_version_index = next(
        i
        for i, step in enumerate(release_steps)
        if isinstance(step, dict) and step.get("name") == "Compute version"
    )
    assert setup_index < compute_version_index
    assert setup_index < build_ui_index

    main_release_text = _MAIN_RELEASE.read_text(encoding="utf-8")
    assert "publish_wiki" not in main_release["jobs"]
    assert "steps.setup-python.outputs.python-path" in main_release_text
    assert "tools/release/main_release.py compute-version" in main_release_text
    assert "tools/release/main_release.py build-wheel" in main_release_text
    assert "tools/release/main_release.py generate-firmware-manifest" in main_release_text
    assert "tools/release/main_release.py cleanup-releases" in main_release_text

    weekly_text = _WEEKLY_PI_IMAGE.read_text(encoding="utf-8")
    assert "uses: ./.github/actions/build-pi-image" in weekly_text

    manual_text = _MANUAL_PI_IMAGE.read_text(encoding="utf-8")
    assert "uses: ./.github/actions/build-pi-image" in manual_text

    build_pi_image_text = _BUILD_PI_IMAGE.read_text(encoding="utf-8")
    assert "steps.setup-python.outputs.python-path" in build_pi_image_text
    assert "VS_PYTHON_BIN: ${{ steps.setup-python.outputs.python-path }}" in build_pi_image_text
    assert "python3 " not in build_pi_image_text

    ci_text = _CI.read_text(encoding="utf-8")
    assert "steps.setup-python.outputs.python-path" in ci_text
    assert "steps.setup-backend.outputs.python-path" in ci_text

    ci = _load_yaml(_CI)
    docs_lint_steps = ci["jobs"]["docs-lint"]["steps"]
    assert isinstance(docs_lint_steps, list)
    setup_python_step = next(
        step
        for step in docs_lint_steps
        if isinstance(step, dict) and step.get("id") == "setup-python"
    )
    assert setup_python_step["uses"] == "./.github/actions/setup-python"
    docs_lint_step = next(
        step
        for step in docs_lint_steps
        if isinstance(step, dict) and step.get("name") == "Docs lint"
    )
    assert docs_lint_step["run"] == (
        '"${{ steps.setup-python.outputs.python-path }}" tools/dev/docs_lint.py'
    )


def test_pi_image_release_scripts_accept_configured_python_path() -> None:
    app_artifacts = _APP_ARTIFACTS.read_text(encoding="utf-8")
    assert '"${VS_PYTHON_BIN}" -m venv .build-venv' in app_artifacts
    assert "python3 -m venv" not in app_artifacts

    pi_gen_repo = _PI_GEN_REPO.read_text(encoding="utf-8")
    assert "\"${VS_PYTHON_BIN}\" - <<'PY'" in pi_gen_repo
    assert "python3 - <<'PY'" not in pi_gen_repo

    prereqs = _PREREQS.read_text(encoding="utf-8")
    assert 'require_cmd "${VS_PYTHON_BIN}"' in prereqs
