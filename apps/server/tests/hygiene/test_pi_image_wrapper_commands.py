"""Guard Pi-image wrapper scripts through command outputs and collected artifacts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from _paths import REPO_ROOT

_BUILD_SCRIPT = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "build.sh"
_VALIDATE_SCRIPT = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "validate-image.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _prepare_pi_gen_wrapper_fixture(tmp_path: Path) -> dict[str, Path]:
    pi_gen_root = tmp_path / "pi-gen"
    lib_dir = pi_gen_root / "lib"
    bin_dir = tmp_path / "bin"
    out_dir = pi_gen_root / "out"
    release_dir = tmp_path / "release"
    repo_root = tmp_path / "repo"
    lib_dir.mkdir(parents=True)
    bin_dir.mkdir()
    out_dir.mkdir(parents=True)
    repo_root.mkdir()

    _write_executable(pi_gen_root / "build.sh", _BUILD_SCRIPT.read_text(encoding="utf-8"))
    _write_executable(
        pi_gen_root / "validate-image.sh", _VALIDATE_SCRIPT.read_text(encoding="utf-8")
    )

    common_sh = f"""REPO_ROOT="${{REPO_ROOT:-{repo_root}}}"
OUT_DIR="${{OUT_DIR:-{out_dir}}}"
COPY_ARTIFACT_DIR="${{COPY_ARTIFACT_DIR:-}}"
VALIDATE="${{VALIDATE:-1}}"
BUILD_MODE="${{BUILD_MODE:-all}}"
IMG_SUFFIX="-vibesensor-lite"

init_pi_gen_env() {{ :; }}
validate_build_mode() {{
  case "${{BUILD_MODE}}" in
    app|image|all) ;;
    *) echo "Invalid BUILD_MODE: ${{BUILD_MODE}}" >&2; exit 1 ;;
  esac
}}
ensure_output_dirs() {{ mkdir -p "${{OUT_DIR}}"; }}
apply_fast_mode() {{ :; }}
validate_first_user_credentials() {{ :; }}
require_cmd() {{ :; }}
"""
    (lib_dir / "common.sh").write_text(common_sh, encoding="utf-8")
    (lib_dir / "prereqs.sh").write_text(
        "\n".join(
            (
                "require_app_prereqs() { :; }",
                "require_image_prereqs() { :; }",
                "ensure_docker_available() { :; }",
                "require_validation_prereqs() { :; }",
                "",
            )
        ),
        encoding="utf-8",
    )
    (lib_dir / "mirror.sh").write_text(
        "select_raspbian_mirror() { printf '%s\\n' 'https://mirror.invalid/raspbian'; }\n",
        encoding="utf-8",
    )
    (lib_dir / "app_artifacts.sh").write_text(
        "\n".join(
            (
                'build_app_artifacts() { printf "app\\n" > "${OUT_DIR}/app-built.txt"; }',
                "require_prebuilt_app_artifacts() { :; }",
                "",
            )
        ),
        encoding="utf-8",
    )
    (lib_dir / "pi_gen_repo.sh").write_text("prepare_pi_gen_repo() { :; }\n", encoding="utf-8")
    (lib_dir / "stage_assembly.sh").write_text(
        "\n".join(
            (
                "prepare_pi_gen_stage() { :; }",
                "configure_incremental_build() { :; }",
                (
                    "run_pi_gen_build() { "
                    'printf "image\\n" > "${OUT_DIR}/image_2026-04-29-vibesensor-lite.img.zip"; '
                    "}"
                ),
                "copy_exported_image_artifacts() { :; }",
                "",
            )
        ),
        encoding="utf-8",
    )
    (lib_dir / "artifacts.sh").write_text(
        "\n".join(
            (
                "choose_final_artifact() {",
                '  local base_dir="$1"',
                '  local artifact="${base_dir}/image_2026-04-29-vibesensor-lite.img.zip"',
                '  [ -f "${artifact}" ] || return 1',
                '  printf "%s\\n" "${artifact}"',
                "}",
                "write_version_info() {",
                '  local version_info_file="$1"',
                '  local final_artifact="$2"',
                '  local build_git_sha="$4"',
                '  local build_git_branch="$5"',
                "  {",
                '    echo "git_sha=${build_git_sha}"',
                '    echo "git_branch=${build_git_branch}"',
                '    echo "source_artifact=$(basename "${final_artifact}")"',
                '  } > "${version_info_file}"',
                "}",
                "prune_old_artifacts() { :; }",
                "",
            )
        ),
        encoding="utf-8",
    )
    (lib_dir / "image_validation.sh").write_text(
        "\n".join(
            (
                "validate_image_artifact() {",
                '  local artifact="$1"',
                '  printf "%s\\n" "${artifact}" > "${OUT_DIR}/validated-artifact.txt"',
                "}",
                "",
            )
        ),
        encoding="utf-8",
    )

    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "-C" ]; then
  shift 2
fi
case "$*" in
  "rev-parse --short=12 HEAD") printf '%s\n' 'deadbeefcafe' ;;
  "rev-parse --abbrev-ref HEAD") printf '%s\n' 'main' ;;
  *) echo "unexpected git args: $*" >&2; exit 1 ;;
esac
""",
    )

    return {
        "build": pi_gen_root / "build.sh",
        "validate": pi_gen_root / "validate-image.sh",
        "out": out_dir,
        "release": release_dir,
        "bin": bin_dir,
    }


def _run_wrapper(
    script_path: Path,
    *,
    bin_dir: Path,
    extra_env: dict[str, str] | None = None,
    args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script_path), *(args or [])],
        cwd=script_path.parent,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_build_wrapper_app_mode_finishes_after_app_artifacts(tmp_path: Path) -> None:
    paths = _prepare_pi_gen_wrapper_fixture(tmp_path)

    result = _run_wrapper(
        paths["build"],
        bin_dir=paths["bin"],
        extra_env={"BUILD_MODE": "app"},
    )

    assert result.returncode == 0, result.stderr
    assert "Build mode 'app' complete." in result.stdout
    assert (paths["out"] / "app-built.txt").is_file()
    assert not (paths["out"] / "validated-artifact.txt").exists()
    assert "Final artifact:" not in result.stdout


def test_build_wrapper_reports_final_artifact_and_copies_release_files(tmp_path: Path) -> None:
    paths = _prepare_pi_gen_wrapper_fixture(tmp_path)
    release_dir = paths["release"]
    artifact = paths["out"] / "image_2026-04-29-vibesensor-lite.img.zip"
    version_info = paths["out"] / f"{artifact.name}.version.txt"

    result = _run_wrapper(
        paths["build"],
        bin_dir=paths["bin"],
        extra_env={
            "BUILD_MODE": "image",
            "COPY_ARTIFACT_DIR": str(release_dir),
        },
    )

    assert result.returncode == 0, result.stderr
    assert artifact.is_file()
    assert version_info.is_file()
    assert (paths["out"] / "validated-artifact.txt").read_text(encoding="utf-8").strip() == str(
        artifact
    )
    assert (release_dir / artifact.name).is_file()
    assert (release_dir / version_info.name).is_file()
    assert (release_dir / artifact.name).read_text(encoding="utf-8") == "image\n"
    assert "Using Raspbian mirror: https://mirror.invalid/raspbian" in result.stdout
    assert f"Final artifact: {artifact}" in result.stdout
    assert f"Version info: {version_info}" in result.stdout


def test_validate_image_wrapper_uses_selected_artifact_and_reports_completion(
    tmp_path: Path,
) -> None:
    paths = _prepare_pi_gen_wrapper_fixture(tmp_path)
    artifact = paths["out"] / "image_2026-04-29-vibesensor-lite.img.zip"
    artifact.write_text("image\n", encoding="utf-8")

    result = _run_wrapper(paths["validate"], bin_dir=paths["bin"])

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"Validation complete for: {artifact}"
    assert "Final artifact:" not in result.stdout
    assert (paths["out"] / "validated-artifact.txt").read_text(encoding="utf-8").strip() == str(
        artifact
    )
