"""Guard pi-gen artifact selection priority and legacy artifact-name rejection."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from _paths import REPO_ROOT

_ARTIFACTS_SH = REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "artifacts.sh"
_IMG_SUFFIX = "-vibesensor-lite"


def _choose_final_artifact(base_dir: Path) -> subprocess.CompletedProcess[str]:
    script = "\n".join(
        (
            "set -euo pipefail",
            f"IMG_SUFFIX={shlex.quote(_IMG_SUFFIX)}",
            f"source {shlex.quote(str(_ARTIFACTS_SH))}",
            f"choose_final_artifact {shlex.quote(str(base_dir))}",
        )
    )
    return subprocess.run(
        ["bash", "-lc", script],
        check=False,
        capture_output=True,
        text=True,
    )


def test_choose_final_artifact_prefers_current_image_priority(tmp_path: Path) -> None:
    (tmp_path / f"image_2026-03-21{_IMG_SUFFIX}.zip").write_text("", encoding="utf-8")
    (tmp_path / f"image_2026-03-21{_IMG_SUFFIX}.img.xz").write_text("", encoding="utf-8")
    (tmp_path / f"image_2026-03-21{_IMG_SUFFIX}.img").write_text("", encoding="utf-8")

    result = _choose_final_artifact(tmp_path)

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).name == f"image_2026-03-21{_IMG_SUFFIX}.img"
    assert result.stderr == ""


def test_choose_final_artifact_prefers_image_prefixed_zip_over_legacy_name(tmp_path: Path) -> None:
    (tmp_path / f"legacy-build{_IMG_SUFFIX}.zip").write_text("", encoding="utf-8")
    (tmp_path / f"image_2026-03-21{_IMG_SUFFIX}.zip").write_text("", encoding="utf-8")

    result = _choose_final_artifact(tmp_path)

    assert result.returncode == 0, result.stderr
    assert Path(result.stdout.strip()).name == f"image_2026-03-21{_IMG_SUFFIX}.zip"


def test_choose_final_artifact_rejects_legacy_non_image_zip_names(tmp_path: Path) -> None:
    (tmp_path / f"legacy-build{_IMG_SUFFIX}.zip").write_text("", encoding="utf-8")

    result = _choose_final_artifact(tmp_path)

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == ""
