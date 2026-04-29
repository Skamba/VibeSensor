from __future__ import annotations

import asyncio
import hashlib
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from _update_manager_test_helpers import (
    assert_hotspot_restored,
    make_mock_release,
    patch_release_fetcher,
    patch_validation_environment,
    run_update,
    seed_runtime_artifacts,
    setup_update_env,
)

from vibesensor.shared.exceptions import UpdateCleanupError
from vibesensor.use_cases.updates.models import UpdateState, UpdateTransport, UsbInternetStatus
from vibesensor.use_cases.updates.status import collect_runtime_details, update_status_to_builtins


class _StaticUsbInternetService:
    def __init__(self, status: UsbInternetStatus) -> None:
        self._status = status

    async def snapshot(self, *, activate: bool = False) -> UsbInternetStatus:
        del activate
        return self._status


def _build_fake_wheel(path, *, version: str) -> bytes:
    dist_info = f"vibesensor-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as wheel_zip:
        wheel_zip.writestr("vibesensor/__init__.py", f"__version__ = '{version}'\n")
        wheel_zip.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.1\nName: vibesensor\nVersion: {version}\n",
        )
        wheel_zip.writestr(f"{dist_info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n")
    return path.read_bytes()


@pytest.mark.asyncio
class TestUpdateManagerAsync:
    async def test_happy_path(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _repo = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            (tmp_path / "rollback").mkdir()

            mock_wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
            wheel_content = _build_fake_wheel(mock_wheel_path, version="2025.6.15")
            wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()
            mock_release = make_mock_release(sha256=wheel_sha256)
            fetcher.find_latest_release.return_value = mock_release
            fetcher.download_wheel.return_value = mock_wheel_path
            runner.set_response("from vibesensor import __version__", 0, "2025.6.15", "")
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        assert manager.status.exit_code == 0
        assert [
            call[0]
            for call in runner.calls
            if "pip" in " ".join(call[0]) and "install" in " ".join(call[0])
        ]
        assert_hotspot_restored(runner)
        fw_mod = "vibesensor.use_cases.updates.firmware.firmware_cache"
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
        manager, runner, _ = setup_update_env(tmp_path, sudo_ok=False, rollback=False)
        runner.set_response("python3 -c pass", 1, "", "sudo: a password is required")
        with patch(
            "vibesensor.use_cases.updates.release_resolution.ServerReleaseResolver.resolve",
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
        assert_hotspot_restored(runner)

    async def test_wifi_ssid_not_found_retries_then_succeeds(self, tmp_path) -> None:
        with (
            patch_release_fetcher() as fetcher,
            patch(
                "vibesensor.use_cases.updates.wifi.wifi_uplink_setup.asyncio.sleep",
                new=AsyncMock(return_value=None),
            ),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            original_run = runner.run
            connect_calls = {"count": 0}

            async def run_with_retry(args, *, timeout=30, env=None):
                joined = " ".join(args)
                if "connection up VibeSensor-Uplink" in joined:
                    connect_calls["count"] += 1
                    if connect_calls["count"] == 1:
                        return (10, "", "Error: No network with SSID 'TestNet' found.\n")
                return await original_run(args, timeout=timeout, env=env)

            runner.run = run_with_retry
            fetcher.find_latest_release.return_value = make_mock_release()
            manager.start("TestNet", "pass123")
            task = manager.job_task
            assert task is not None
            await asyncio.wait_for(task, timeout=10)

        assert manager.status.state == UpdateState.success
        assert connect_calls["count"] >= 2

    async def test_dns_not_ready_fails_with_clear_issue(self, tmp_path) -> None:
        with (
            patch_release_fetcher() as fetcher,
            patch("vibesensor.use_cases.updates.wifi.wifi_config.DNS_READY_MIN_WAIT_S", 0.05),
            patch("vibesensor.use_cases.updates.wifi.wifi_config.DNS_RETRY_INTERVAL_S", 0.01),
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
        probe_attempts = {"count": 0}
        with (
            patch_release_fetcher() as fetcher,
            patch("vibesensor.use_cases.updates.wifi.wifi_config.DNS_READY_MIN_WAIT_S", 0.2),
            patch("vibesensor.use_cases.updates.wifi.wifi_config.DNS_RETRY_INTERVAL_S", 0.01),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            original_run = runner.run

            async def run_with_dns_retry(args, *, timeout=30, env=None):
                if "socket.getaddrinfo" in " ".join(args):
                    probe_attempts["count"] += 1
                    if probe_attempts["count"] < 3:
                        return (1, "", "Temporary failure in name resolution")
                return await original_run(args, timeout=timeout, env=env)

            runner.run = run_with_dns_retry
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        assert probe_attempts["count"] >= 3

    async def test_secure_ssid_requires_password(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response("dev wifi list", 0, "Pim:WPA2\n")
        await run_update(manager, "Pim", "")
        assert manager.status.state == UpdateState.failed

    async def test_password_is_applied_via_connection_modify(self, tmp_path) -> None:
        with patch_release_fetcher() as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            await run_update(manager, "Pim", "tomaat123")
        assert any(
            "connection modify VibeSensor-Uplink "
            "wifi-sec.key-mgmt wpa-psk wifi-sec.psk" in " ".join(call[0])
            for call in runner.calls
        )

    async def test_download_failure_still_restores_hotspot(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            mock_release = make_mock_release(sha256="abc")
            fetcher.find_latest_release.return_value = mock_release
            fetcher.download_wheel.side_effect = OSError("Network error")
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        assert_hotspot_restored(runner)

    async def test_install_failure_triggers_rollback(self, tmp_path) -> None:
        with patch_release_fetcher(current_version="2025.6.14") as fetcher:
            manager, runner, _ = setup_update_env(
                tmp_path,
                server_release_fetcher=fetcher,
            )
            runner.set_response("pip", 1, "", "ERROR: Could not install")
            (tmp_path / "rollback").mkdir()
            fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
            wheel_content = _build_fake_wheel(fake_wheel, version="2025.6.15")
            wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()
            fetcher.find_latest_release.return_value = make_mock_release(sha256=wheel_sha256)
            fetcher.download_wheel.return_value = fake_wheel
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed

    async def test_snapshot_failure_aborts_before_install(self, tmp_path) -> None:
        with (
            patch_release_fetcher(current_version="2025.6.14") as fetcher,
            patch(
                "vibesensor.use_cases.updates.installer.UpdateInstaller.snapshot_for_rollback",
                new=AsyncMock(return_value=False),
            ),
        ):
            manager, runner, _ = setup_update_env(
                tmp_path,
                seed_artifacts=True,
                server_release_fetcher=fetcher,
            )
            fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
            wheel_content = _build_fake_wheel(fake_wheel, version="2025.6.15")
            wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()
            fetcher.find_latest_release.return_value = make_mock_release(sha256=wheel_sha256)
            fetcher.download_wheel.return_value = fake_wheel
            await run_update(manager, "TestNet", "pass")

        assert manager.status.state == UpdateState.failed
        pip_install_calls = [
            call[0]
            for call in runner.calls
            if "pip" in " ".join(call[0]) and "install" in " ".join(call[0])
        ]
        assert not pip_install_calls

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
            fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
            fake_wheel.write_bytes(b"fake-wheel-content")
            fetcher.find_latest_release.return_value = make_mock_release(sha256="0" * 64)
            fetcher.download_wheel.return_value = fake_wheel
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        pip_calls = [
            call[0]
            for call in runner.calls
            if "pip" in " ".join(call[0]) and "install" in " ".join(call[0])
        ]
        assert not pip_calls
        assert_hotspot_restored(runner)

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
            patch("vibesensor.use_cases.updates.runtime.UPDATE_TIMEOUT_S", 0.5),
            patch("vibesensor.use_cases.updates.wifi.wifi_config.HOTSPOT_RESTORE_RETRIES", 1),
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
        manager, _runner, _ = setup_update_env(tmp_path)

        with (
            patch(
                "vibesensor.use_cases.updates.runtime_refresh.collect_runtime_details",
                side_effect=OSError("runtime unavailable"),
            ),
            patch.object(
                type(manager._workflow.preparation),
                "prepare",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        prepared_transport=AsyncMock(),
                    )
                ),
            ),
            patch.object(
                type(manager._workflow.release_planner),
                "plan",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
            caplog.at_level("ERROR"),
        ):
            manager.start("TestNet", "pass123")
            assert manager.job_task is not None
            with pytest.raises(
                UpdateCleanupError,
                match="Cleanup failed after cancellation: Runtime details refresh failed",
            ):
                await manager.job_task

        assert manager.status.finished_at is not None
        assert manager.status.state == UpdateState.failed
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
        manager, _runner, _ = setup_update_env(tmp_path)

        with (
            patch(
                "vibesensor.use_cases.updates.runtime_refresh.collect_runtime_details",
                side_effect=TypeError("runtime bug"),
            ),
            patch.object(
                type(manager._workflow.preparation),
                "prepare",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        prepared_transport=AsyncMock(),
                    )
                ),
            ),
            patch.object(
                type(manager._workflow.release_planner),
                "plan",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            manager.start("TestNet", "pass123")
            assert manager.job_task is not None
            with pytest.raises(TypeError, match="runtime bug"):
                await manager.job_task

        assert manager.status.finished_at is not None
        assert manager.status.state == UpdateState.failed

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
        manager, _runner, _ = setup_update_env(tmp_path, sudo_ok=False, rollback=False)

        def which_without(name: str) -> str | None:
            return None if name == missing_tool else f"/usr/bin/{name}"

        await run_update(manager, "TestNet", "pass", tool_lookup=which_without)
        assert manager.status.state == UpdateState.failed
