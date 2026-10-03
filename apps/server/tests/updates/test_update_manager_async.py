from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from _update_manager_test_helpers import (
    make_mock_release,
    patch_release_fetcher,
    patch_validation_environment,
    publish_release,
    run_update,
    seed_runtime_artifacts,
    setup_update_env,
)
from test_support.venv_slots import add_slot

from vibesensor.updates.job import UpdateJob
from vibesensor.updates.manager import UpdateManager
from vibesensor.updates.models import (
    UpdatePhase,
    UpdateState,
    UpdateTerminalState,
    UpdateTransport,
    UpdateValidationConfig,
    UsbInternetStatus,
)
from vibesensor.updates.status.payload_codec import (
    UpdateStateStore,
    update_status_to_builtins,
)
from vibesensor.updates.status.runtime_details import collect_runtime_details
from vibesensor.updates.status.tracker import UpdateStatusTracker
from vibesensor.updates.transport.coordinator import UpdateTransportCoordinator
from vibesensor.updates.venv_slots import VenvSlots


class _StaticUsbInternetService:
    def __init__(self, status: UsbInternetStatus) -> None:
        self._status = status

    async def snapshot(self, *, activate: bool = False) -> UsbInternetStatus:
        del activate
        return self._status


def _assert_hotspot_restore_logged(manager: UpdateManager) -> None:
    assert any("Hotspot restored on attempt" in line for line in manager.status.log_tail)


def _build_manager_with_cancellation_cleanup(
    tmp_path,
) -> tuple[UpdateManager, UpdateStateStore]:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_store = UpdateStateStore(tmp_path / "update_status.json")
    tracker = UpdateStatusTracker(state_store=state_store)
    prepared_transport = SimpleNamespace(cleanup_after_update=AsyncMock())

    async def prepare(_request):
        tracker.transition(UpdatePhase.stopping_hotspot)
        tracker.transition(UpdatePhase.connecting_wifi)
        return prepared_transport

    def cancel_release_check():
        raise asyncio.CancelledError

    lifecycle = SimpleNamespace(prepare=prepare)
    job = UpdateJob(
        status=tracker,
        commands=MagicMock(),
        transport=UpdateTransportCoordinator(
            wifi=lifecycle,
            usb_internet=lifecycle,
            logger=logging.getLogger("vibesensor.tests.update_cleanup"),
        ),
        release_fetcher=SimpleNamespace(find_latest_release=cancel_release_check),
        stager=MagicMock(),
        firmware_refresher=MagicMock(),
        installer=MagicMock(),
        slots=MagicMock(),
        validation_config=UpdateValidationConfig(
            venv_root=tmp_path / "venv",
            min_free_disk_bytes=1,
        ),
        repo=repo,
    )
    manager = UpdateManager(
        status=tracker,
        job=job,
        usb_status_service=MagicMock(),
        timeout_s=10.0,
    )
    return manager, state_store


@pytest.mark.asyncio
class TestUpdateManagerAsync:
    async def test_happy_path(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _repo = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )

            publish_release(fetcher, tmp_path / "assets")
            runner.set_response("from vibesensor import __version__", 0, "2025.6.15", "")
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        assert manager.status.exit_code == 0
        slots = VenvSlots(_repo / "apps" / "server" / ".venv")
        new_python = str(slots.slot_python("2025.6.15"))
        assert any(call[0][:4] == [new_python, "-m", "pip", "install"] for call in runner.calls)
        assert any("smoke-server" in call[0] for call in runner.calls)
        assert slots.active_slot() == "2025.6.15"
        pending = slots.pending_boot()
        assert pending is not None and pending.previous == "2025.6.14"
        _assert_hotspot_restore_logged(manager)
        fw_mod = "vibesensor.updates.firmware.firmware_cache"
        firmware_refresh_calls = [call[0] for call in runner.calls if fw_mod in " ".join(call[0])]
        assert firmware_refresh_calls
        restart_cmd = (
            "systemd-run --unit vibesensor-post-update-restart --on-active=2s "
            "systemctl restart vibesensor.service"
        )
        assert any(restart_cmd in " ".join(call[0]) for call in runner.calls)

    async def test_already_up_to_date(self, tmp_path) -> None:
        with patch_release_fetcher() as fetcher:
            manager, runner, _repo = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        pip_install_calls = [
            call[0]
            for call in runner.calls
            if "pip" in " ".join(call[0]) and "force-reinstall" in " ".join(call[0])
        ]
        assert not pip_install_calls

    async def test_no_sudo_fails_gracefully(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path, sudo_ok=False)
        runner.set_response("python3 -c pass", 1, "", "sudo: a password is required")
        with patch(
            "vibesensor.updates.job.UpdateJob._find_latest_release",
            side_effect=AssertionError("release resolution should not run without privileges"),
        ):
            await run_update(manager, "TestNet", "pass", effective_uid=1000)
        assert manager.status.state == UpdateState.failed
        assert (
            "privileg"
            in " ".join(
                f"{issue.message} {issue.detail}" for issue in manager.status.issues
            ).lower()
        )

    async def test_wifi_connection_failure(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response(
            "connection up VibeSensor-Uplink",
            1,
            "",
            "Error: Connection activation failed",
        )
        await run_update(manager, "BadNet", "wrong")
        assert manager.status.state == UpdateState.failed
        _assert_hotspot_restore_logged(manager)

    async def test_wifi_ssid_not_found_retries_then_succeeds(self, tmp_path) -> None:
        with (
            patch_release_fetcher() as fetcher,
            patch("vibesensor.updates.wifi.wifi_config.UPLINK_RESCAN_DELAY_S", 0.0),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            runner.set_response_sequence(
                "connection up VibeSensor-Uplink",
                (10, "", "Error: No network with SSID 'TestNet' found.\n"),
                (0, "", ""),
            )
            fetcher.find_latest_release.return_value = make_mock_release()
            manager.start("TestNet", "pass123")
            task = manager.job_task
            assert task is not None
            await asyncio.wait_for(task, timeout=10)

        assert manager.status.state == UpdateState.success
        assert any("rescanning and retrying" in line for line in manager.status.log_tail)

    async def test_dns_not_ready_fails_with_clear_issue(self, tmp_path) -> None:
        with (
            patch_release_fetcher() as fetcher,
            patch("vibesensor.updates.wifi.wifi_config.DNS_READY_MIN_WAIT_S", 0.05),
            patch("vibesensor.updates.wifi.wifi_config.DNS_RETRY_INTERVAL_S", 0.01),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            runner.set_response("socket.getaddrinfo", 1, "", "Temporary failure in name resolution")
            await run_update(manager)
            fetcher.find_latest_release.assert_not_called()
        assert manager.status.state == UpdateState.failed

    async def test_dns_probe_retries_then_update_continues(self, tmp_path) -> None:
        with (
            patch_release_fetcher() as fetcher,
            patch("vibesensor.updates.wifi.wifi_config.DNS_READY_MIN_WAIT_S", 1.0),
            patch("vibesensor.updates.wifi.wifi_config.DNS_RETRY_INTERVAL_S", 0.0),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            runner.set_response_sequence(
                "socket.getaddrinfo",
                (1, "", "Temporary failure in name resolution"),
                (1, "", "Temporary failure in name resolution"),
                (0, "", ""),
            )
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        assert any("DNS probe succeeded on attempt 3" in line for line in manager.status.log_tail)

    async def test_secure_ssid_requires_password(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response("dev wifi list", 0, "Pim:WPA2\n")
        await run_update(manager, "Pim", "")
        assert manager.status.state == UpdateState.failed

    async def test_password_configuration_failure_fails_update(self, tmp_path) -> None:
        with patch_release_fetcher() as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            runner.set_response("wifi-sec.psk", 10, "", "failed to set Wi-Fi credentials")
            await run_update(manager, "Pim", "tomaat123")
        assert manager.status.state == UpdateState.failed
        assert any(
            issue.message == "Failed to set Wi-Fi credentials" for issue in manager.status.issues
        )

    async def test_download_failure_still_restores_hotspot(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            publish_release(fetcher, tmp_path / "assets")
            fetcher.download_asset.side_effect = OSError("Network error")
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        _assert_hotspot_restore_logged(manager)

    async def test_install_failure_keeps_the_live_slot(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, repo = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            runner.set_response("pip", 1, "", "ERROR: Could not install")
            publish_release(fetcher, tmp_path / "assets")
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        slots = VenvSlots(repo / "apps" / "server" / ".venv")
        assert slots.active_slot() == "2025.6.14"
        assert not slots.slot_dir("2025.6.15").exists()
        assert slots.pending_boot() is None
        _assert_hotspot_restore_logged(manager)

    async def test_update_waits_while_the_previous_one_is_in_its_boot_check(
        self,
        tmp_path,
    ) -> None:
        manager, runner, repo = setup_update_env(tmp_path)
        slots = VenvSlots(repo / "apps" / "server" / ".venv")
        slots.adopt("2025.6.14")
        add_slot(slots, "2025.6.15")
        slots.activate("2025.6.15", health_url="http://127.0.0.1:80/api/health")

        await run_update(manager, "TestNet", "pass")

        assert manager.status.state == UpdateState.failed
        assert manager.status.issues[0].message == "The previous update is still being verified"
        assert not any("nmcli" in call[0] for call in runner.calls)

    async def test_disk_check_failure_aborts_update(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        with patch("shutil.disk_usage", side_effect=OSError("statfs failed")):
            await run_update(manager, "TestNet", "pass")

        assert manager.status.state == UpdateState.failed
        assert all(
            not ("pip" in " ".join(call[0]) and "install" in " ".join(call[0]))
            for call in runner.calls
        )
        assert any(
            issue.message == "Could not verify free disk space" for issue in manager.status.issues
        )

    async def test_sha256_mismatch_aborts_install(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            publish_release(fetcher, tmp_path / "assets", wheel_sha256="0" * 64)
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        pip_calls = [
            call[0]
            for call in runner.calls
            if "pip" in " ".join(call[0]) and "install" in " ".join(call[0])
        ]
        assert not pip_calls
        _assert_hotspot_restore_logged(manager)

    async def test_password_never_in_logs(self, tmp_path) -> None:
        secret = "SuperSecret!Password#2024"
        with patch_release_fetcher() as fetcher:
            manager, _runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            await run_update(manager, "TestNet", secret)
        serialized = str(update_status_to_builtins(manager.status))
        assert secret not in serialized
        for line in manager.status.log_tail:
            assert secret not in line
        for issue in manager.status.issues:
            assert secret not in issue.message
            assert secret not in issue.detail

    async def test_stale_public_assets_detected_in_runtime(self, tmp_path) -> None:
        manager, _runner, repo = setup_update_env(tmp_path)
        seed_runtime_artifacts(repo, manager, valid=False)
        details = collect_runtime_details(repo)
        assert details.assets_verified is False

    async def test_runtime_details_report_current_package_version(self, tmp_path) -> None:
        manager, _runner, repo = setup_update_env(tmp_path)
        seed_runtime_artifacts(repo, manager)

        with patch("vibesensor.__version__", "2026.3.29"):
            details = collect_runtime_details(repo)

        assert details.version == "2026.3.29"

    async def test_runtime_details_ignore_corrupt_ui_build_metadata(self, tmp_path) -> None:
        manager, _runner, repo = setup_update_env(tmp_path)
        seed_runtime_artifacts(repo, manager)
        metadata_path = (
            repo / "apps" / "server" / "vibesensor" / "static" / ".vibesensor-ui-build.json"
        )
        metadata_path.write_text("{not-json", encoding="utf-8")

        details = collect_runtime_details(repo)

        assert details.static_build_source_hash == ""
        assert details.static_build_commit == ""
        assert details.assets_verified is False

    async def test_runtime_details_default_blank_for_missing_ui_build_metadata_fields(
        self,
        tmp_path,
    ) -> None:
        manager, _runner, repo = setup_update_env(tmp_path)
        seed_runtime_artifacts(repo, manager)
        metadata_path = (
            repo / "apps" / "server" / "vibesensor" / "static" / ".vibesensor-ui-build.json"
        )
        metadata_path.write_text('{"static_assets_hash":"assets-only"}\n', encoding="utf-8")

        details = collect_runtime_details(repo)

        assert details.static_build_source_hash == ""
        assert details.static_build_commit == ""
        assert details.assets_verified is False

    async def test_usb_internet_happy_path_skips_hotspot_handover(self, tmp_path) -> None:
        usb_service = _StaticUsbInternetService(
            UsbInternetStatus(
                detected=True,
                usable=True,
                interface_name="usb0",
                connection_name="iPhone USB",
                driver="ipheth",
                ipv4_addresses=("172.20.10.2/28",),
                gateway="172.20.10.1",
                has_default_route=True,
                diagnostic="USB internet is ready on 'usb0'.",
            )
        )
        with patch_release_fetcher() as fetcher:
            manager, runner, _repo = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                usb_internet_service=usb_service,
                server_release_fetcher=fetcher,
            )
            await run_update(manager, transport=UpdateTransport.usb_internet)

        assert manager.status.state == UpdateState.success
        assert manager.status.transport == UpdateTransport.usb_internet
        assert manager.status.uplink_interface == "usb0"
        commands = [" ".join(call[0]) for call in runner.calls]
        assert not any("VibeSensor-AP" in command for command in commands)
        assert not any("VibeSensor-Uplink" in command for command in commands)

    async def test_usb_internet_unusable_fails_before_release_check(self, tmp_path) -> None:
        usb_service = _StaticUsbInternetService(
            UsbInternetStatus(
                detected=True,
                usable=False,
                interface_name="usb0",
                connection_name="iPhone USB",
                driver="ipheth",
                ipv4_addresses=("172.20.10.2/28",),
                gateway=None,
                has_default_route=False,
                diagnostic=(
                    "USB interface 'usb0' is connected, but no default IPv4 route is active."
                ),
            )
        )
        with patch_release_fetcher() as fetcher:
            manager, runner, _repo = setup_update_env(
                tmp_path,
                usb_internet_service=usb_service,
                server_release_fetcher=fetcher,
            )
            await run_update(manager, transport=UpdateTransport.usb_internet)
            fetcher.find_latest_release.assert_not_called()

        assert manager.status.state == UpdateState.failed
        assert manager.status.transport == UpdateTransport.usb_internet
        assert any(
            issue.message == "USB internet detected but not usable"
            for issue in manager.status.issues
        )
        commands = [" ".join(call[0]) for call in runner.calls]
        assert not any("VibeSensor-AP" in command for command in commands)
        assert not any("VibeSensor-Uplink" in command for command in commands)

    async def test_timeout_handling(self, tmp_path) -> None:
        with (
            patch_validation_environment(),
            patch("vibesensor.updates.runtime.UPDATE_TIMEOUT_S", 0.5),
            patch("vibesensor.updates.wifi.wifi_config.HOTSPOT_RESTORE_RETRIES", 1),
        ):
            manager, runner, _ = setup_update_env(tmp_path)
            original_run = runner.run

            async def slow_run(args, *, timeout=30, env=None):
                if "connection up VibeSensor-Uplink" in " ".join(args):
                    await asyncio.sleep(300)
                    return (0, "", "")
                return await original_run(args, timeout=timeout, env=env)

            runner.run = slow_run
            manager.start("TestNet", "pass")
            task = manager.job_task
            assert task is not None
            await asyncio.wait_for(task, timeout=3)
        assert manager.status.state == UpdateState.failed

    async def test_run_update_marks_failed_when_cancellation_cleanup_reports_operational_error(
        self,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        manager, state_store = _build_manager_with_cancellation_cleanup(tmp_path)

        with (
            patch(
                "vibesensor.updates.job.validate_prerequisites",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "vibesensor.updates.job.collect_runtime_details",
                side_effect=OSError("runtime unavailable"),
            ),
            caplog.at_level("ERROR"),
        ):
            manager.start("TestNet", "pass123")
            assert manager.job_task is not None
            await manager.job_task

        assert manager.status.finished_at is not None
        assert manager.status.state == UpdateState.failed
        assert manager.status.terminal_state == UpdateTerminalState.cancelled_cleanup_failed
        persisted = state_store.load()
        assert persisted is not None
        assert persisted.state == UpdateState.failed
        assert persisted.terminal_state == UpdateTerminalState.cancelled_cleanup_failed
        assert any(
            issue.message == "Cleanup failed after cancellation: Runtime details refresh failed"
            and issue.detail == ""
            for issue in manager.status.issues
        )
        refresh_log = next(
            rec for rec in caplog.records if rec.message == "update: runtime details refresh error"
        )
        assert refresh_log.event == "update_runtime_refresh_error"
        assert refresh_log.update_phase == "cleanup"
        assert refresh_log.repo_path == str(tmp_path / "repo")

    async def test_run_update_surfaces_programmer_bug_from_cancellation_cleanup(
        self,
        tmp_path,
    ) -> None:
        manager, state_store = _build_manager_with_cancellation_cleanup(tmp_path)

        with (
            patch(
                "vibesensor.updates.job.validate_prerequisites",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "vibesensor.updates.job.collect_runtime_details",
                side_effect=TypeError("runtime bug"),
            ),
        ):
            manager.start("TestNet", "pass123")
            assert manager.job_task is not None
            with pytest.raises(TypeError, match="runtime bug"):
                await manager.job_task

        assert manager.status.finished_at is not None
        assert manager.status.state == UpdateState.failed
        persisted = state_store.load()
        assert persisted is not None
        assert persisted.state == UpdateState.failed

    async def test_check_update_failure_fails_update(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, _runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            fetcher.find_latest_release.side_effect = OSError("API rate limit exceeded")
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed

    @pytest.mark.parametrize("missing_tool", ["nmcli", "python3"])
    async def test_missing_tool_fails_gracefully(self, tmp_path, missing_tool: str) -> None:
        manager, _runner, _ = setup_update_env(tmp_path, sudo_ok=False)

        def which_without(name: str) -> str | None:
            return None if name == missing_tool else f"/usr/bin/{name}"

        await run_update(manager, "TestNet", "pass", tool_lookup=which_without)
        assert manager.status.state == UpdateState.failed
