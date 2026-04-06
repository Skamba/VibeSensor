"""Guard the Pi image baseline-firmware helper script contract."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT

_STAGE_RUN_TEMPLATE = (
    REPO_ROOT / "infra/pi-image/pi-gen/templates/stage-vibesensor/00-vibesensor/00-run.sh.template"
)


def test_baseline_firmware_script_defines_venv_python_before_metadata_patch() -> None:
    text = _STAGE_RUN_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(
        r"cat >/tmp/vibesensor-fw-baseline\.sh <<'FW_BASELINE_EOF'\n(?P<body>.*?)\nFW_BASELINE_EOF",
        text,
        re.DOTALL,
    )
    assert match is not None

    body = match.group("body")
    venv_python_assignment = 'VENV_PYTHON="/opt/VibeSensor/apps/server/.venv/bin/python"'
    metadata_patch = '"${VENV_PYTHON}" -c "'

    assert venv_python_assignment in body
    assert body.index(venv_python_assignment) < body.index(metadata_patch)
