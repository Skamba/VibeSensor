"""Guard: main release workflow references the live release validation module."""

from __future__ import annotations

from tests._paths import REPO_ROOT

_MAIN_RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
_EXPECTED_MODULE = (
    "vibesensor.use_cases.updates.releases.release_validation "
    "validate-firmware-manifest"
)
_STALE_MODULE = "vibesensor.use_cases.updates.release_validation"


def test_main_release_workflow_uses_release_validation_module_path() -> None:
    text = _MAIN_RELEASE_YML.read_text(encoding="utf-8")

    assert _EXPECTED_MODULE in text
    assert _STALE_MODULE not in text
