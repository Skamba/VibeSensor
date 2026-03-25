from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from _update_manager_test_helpers import FakeRunner

from vibesensor.use_cases.updates.models import UpdateIssue, UpdatePhase, UpdateState
from vibesensor.use_cases.updates.runner import UpdateCommandExecutor
from vibesensor.use_cases.updates.status import UpdateStateStore, UpdateStatusTracker
from vibesensor.use_cases.updates.wifi import UpdateWifiOrchestrator, build_default_wifi_config


def _build_orchestrator(
    tmp_path: Path,
    *,
    restore_retries: int = 3,
    restore_delay_s: float = 0.01,
) -> tuple[UpdateWifiOrchestrator, FakeRunner, UpdateStatusTracker]:
    runner = FakeRunner()
    tracker = UpdateStatusTracker(state_store=UpdateStateStore(tmp_path / "state.json"))
    config = replace(
        build_default_wifi_config(ap_con_name="VibeSensor-AP", wifi_ifname="wlan0"),
        hotspot_restore_retries=restore_retries,
        hotspot_restore_delay_s=restore_delay_s,
    )
    commands = UpdateCommandExecutor(runner=runner, tracker=tracker)
    orchestrator = UpdateWifiOrchestrator(
        commands=commands,
        tracker=tracker,
        config=config,
    )
    return orchestrator, runner, tracker


@pytest.mark.asyncio
async def test_recover_interrupted_update_cleans_uplink_and_restores_hotspot(
    tmp_path: Path,
) -> None:
    orchestrator, runner, tracker = _build_orchestrator(tmp_path)

    await orchestrator.recover_interrupted_update()

    commands = [" ".join(call[0]) for call in runner.calls]
    assert any("connection down VibeSensor-Uplink" in command for command in commands)
    assert any("connection delete VibeSensor-Uplink" in command for command in commands)
    assert any("connection up VibeSensor-AP" in command for command in commands)
    assert any(
        "startup_recover: hotspot restored successfully" in line for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_recover_interrupted_update_records_restore_failure(tmp_path: Path) -> None:
    orchestrator, runner, tracker = _build_orchestrator(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    await orchestrator.recover_interrupted_update()

    assert any(
        issue.message == "Failed to restore hotspot after interrupted update"
        for issue in tracker.status.issues
    )
    assert any(
        "startup_recover: hotspot restore failed" in line for line in tracker.status.log_tail
    )


@pytest.mark.asyncio
async def test_cleanup_restore_hotspot_records_issue_on_failure(tmp_path: Path) -> None:
    orchestrator, runner, tracker = _build_orchestrator(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    await orchestrator.cleanup_restore_hotspot()

    assert any(
        issue.phase == "cleanup" and issue.message == "Failed to restore hotspot during cleanup"
        for issue in tracker.status.issues
    )
    assert any("Cleanup hotspot restore failed" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_collect_cleanup_diagnostics_returns_parsed_issues(tmp_path: Path) -> None:
    orchestrator, _runner, _tracker = _build_orchestrator(tmp_path)
    expected_issues = [
        UpdateIssue(
            phase="diagnostics",
            message="Hotspot summary reports failure",
            detail="status=failed",
        ),
    ]

    with patch(
        "vibesensor.use_cases.updates.wifi.wifi_orchestrator.parse_wifi_diagnostics",
        return_value=expected_issues,
    ):
        assert await orchestrator.collect_cleanup_diagnostics() == expected_issues


@pytest.mark.asyncio
async def test_complete_update_success_restores_hotspot_and_marks_success(tmp_path: Path) -> None:
    orchestrator, _runner, tracker = _build_orchestrator(tmp_path)
    tracker.start_job("TestNet")

    assert await orchestrator.complete_update_success("Update completed successfully") is True

    assert tracker.status.state == UpdateState.success
    assert tracker.status.phase == UpdatePhase.done
    assert any("Update completed successfully" in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_complete_update_success_marks_failed_when_restore_fails(tmp_path: Path) -> None:
    orchestrator, runner, tracker = _build_orchestrator(
        tmp_path,
        restore_retries=1,
        restore_delay_s=0,
    )
    tracker.start_job("TestNet")
    runner.set_response("connection up VibeSensor-AP", 10, "", "failed")

    assert await orchestrator.complete_update_success("Update completed successfully") is False

    assert tracker.status.state == UpdateState.failed


@pytest.mark.asyncio
async def test_cleanup_restore_orchestration_restores_hotspot_when_needed(tmp_path: Path) -> None:
    orchestrator, _runner, tracker = _build_orchestrator(tmp_path)
    tracker.start_job("TestNet")
    tracker.transition(UpdatePhase.installing)

    await orchestrator.maybe_restore_hotspot_during_cleanup()

    assert tracker.status.phase == UpdatePhase.restoring_hotspot
    assert any("Restoring hotspot..." in line for line in tracker.status.log_tail)


@pytest.mark.asyncio
async def test_cleanup_restore_orchestration_skips_restore_when_no_longer_needed(
    tmp_path: Path,
) -> None:
    orchestrator, runner, tracker = _build_orchestrator(tmp_path)
    tracker.start_job("TestNet")
    tracker.mark_success("done")

    await orchestrator.maybe_restore_hotspot_during_cleanup()

    commands = [" ".join(call[0]) for call in runner.calls]
    assert not any("connection up VibeSensor-AP" in command for command in commands)
