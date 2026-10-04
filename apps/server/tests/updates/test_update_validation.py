from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_support.update_status import build_update_status_harness

from vibesensor.common.exceptions import UpdatePreparationError
from vibesensor.updates.boot_check import PENDING_FILE
from vibesensor.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.updates.runner import CommandExecutionResult
from vibesensor.updates.validation import validate_prerequisites


def _mock_which(name: str) -> str | None:
    if name in {"nmcli", "python3"}:
        return f"/usr/bin/{name}"
    return None


class _Commands:
    async def run(self, args, *, timeout, phase, privileged=False, env=None):
        del args, timeout, phase, privileged, env
        return CommandExecutionResult(returncode=0, stdout="", stderr="")


async def _validate(venv_root: Path, *, min_free_disk_bytes: int = 1) -> None:
    await validate_prerequisites(
        commands=_Commands(),
        status=build_update_status_harness(venv_root.parent / "state.json"),
        config=UpdateValidationConfig(
            venv_root=venv_root,
            min_free_disk_bytes=min_free_disk_bytes,
        ),
        request=UpdateRequest(transport=UpdateTransport.wifi, ssid="TestNet", password=""),
    )


@pytest.mark.asyncio
async def test_validation_refuses_while_a_boot_check_is_pending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("shutil.which", _mock_which)
    venv_root = tmp_path / ".venv"
    venv_root.mkdir()
    (venv_root / "current").symlink_to("slots/2.0")
    (venv_root / PENDING_FILE).write_text(
        json.dumps({"candidate": "2.0", "previous": "1.0", "health_url": "http://x"}),
    )

    with pytest.raises(UpdatePreparationError, match="still being verified") as excinfo:
        await _validate(venv_root)

    assert excinfo.value.phase == "validating"
    assert "2.0" in excinfo.value.detail


@pytest.mark.asyncio
async def test_validation_ignores_a_marker_for_a_slot_that_never_became_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("shutil.which", _mock_which)
    venv_root = tmp_path / ".venv"
    venv_root.mkdir()
    (venv_root / "current").symlink_to("slots/1.0")
    (venv_root / PENDING_FILE).write_text(
        json.dumps({"candidate": "2.0", "previous": "1.0", "health_url": "http://x"}),
    )

    await _validate(venv_root)


@pytest.mark.asyncio
async def test_validation_checks_free_space_on_the_venv_filesystem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("shutil.which", _mock_which)
    checked: list[Path] = []

    def _usage(path: Path) -> object:
        checked.append(Path(path))
        return type("Usage", (), {"free": 10 * 1024 * 1024})()

    monkeypatch.setattr("shutil.disk_usage", _usage)

    with pytest.raises(UpdatePreparationError, match="Insufficient disk space"):
        await _validate(tmp_path / "missing" / ".venv", min_free_disk_bytes=600 * 1024 * 1024)

    assert checked == [tmp_path]
