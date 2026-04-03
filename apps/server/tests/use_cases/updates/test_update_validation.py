from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.shared.exceptions import UpdatePreparationError
from vibesensor.use_cases.updates.models import (
    UpdateRequest,
    UpdateTransport,
    UpdateValidationConfig,
)
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.validation import validate_prerequisites


def _mock_which(name: str) -> str | None:
    if name in {"nmcli", "python3"}:
        return f"/usr/bin/{name}"
    return None


class _Commands:
    async def run(self, args, *, timeout, phase, sudo=False, env=None):
        del args, timeout, phase, sudo, env
        return (0, "", "")


@pytest.mark.asyncio
async def test_validation_fails_when_rollback_dir_probe_fails(monkeypatch, tmp_path: Path) -> None:
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))

    def _raise_probe(rollback_dir: Path) -> None:
        raise OSError("readonly")

    monkeypatch.setattr("shutil.which", _mock_which)
    monkeypatch.setattr(
        "vibesensor.use_cases.updates.validation._probe_rollback_dir",
        _raise_probe,
    )

    with pytest.raises(UpdatePreparationError, match="Rollback directory is not writable"):
        await validate_prerequisites(
            commands=_Commands(),
            tracker=tracker,
            config=UpdateValidationConfig(
                rollback_dir=tmp_path / "rollback",
                min_free_disk_bytes=1,
            ),
            request=UpdateRequest(
                transport=UpdateTransport.wifi,
                ssid="TestNet",
                password="",
            ),
        )

    assert tracker.status.state.value == "failed"
    assert any(
        issue.message == "Rollback directory is not writable" for issue in tracker.status.issues
    )
