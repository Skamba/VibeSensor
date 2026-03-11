from __future__ import annotations

import asyncio
import hashlib
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from _update_manager_test_helpers import (
    assert_hotspot_restored,
    make_mock_release,
    mock_which,
    patch_release_fetcher,
    run_update,
    seed_runtime_artifacts,
    setup_update_env,
)

from vibesensor.update.models import UpdateState


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
        manager, runner, _repo = setup_update_env(tmp_path, seed_artifacts=True)
        (tmp_path / "rollback").mkdir()

        mock_wheel_path = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        wheel_content = _build_fake_wheel(mock_wheel_path, version="2025.6.15")
        wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()
        mock_release = make_mock_release(sha256=wheel_sha256)

        with patch_release_fetcher(current_version="2025.6.14") as mock_fetcher:
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = mock_release
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
        firmware_refresh_calls = [
            call[0] for call in runner.calls if "vibesensor.firmware_cache" in " ".join(call[0])
        ]
        assert firmware_refresh_calls
        restart_cmd = (
            "systemd-run --unit vibesensor-post-update-restart --on-active=2s "
            "systemctl restart vibesensor.service"
        )
        assert any(restart_cmd in " ".join(call[0]) for call in runner.calls)

    async def test_already_up_to_date(self, tmp_path) -> None:
        manager, runner, _repo = setup_update_env(tmp_path, seed_artifacts=True)
        with patch_release_fetcher() as mock_fetcher:
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = None
            latest_release = type("Latest", (), {"tag": "server-v2025.6.15"})()
            fetcher.find_latest_release.return_value = latest_release
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
        runner.set_response("sudo -n true", 1, "", "sudo: a password is required")
        with patch("shutil.which", mock_which):
            await run_update(manager, "TestNet", "pass")
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
        with patch("shutil.which", mock_which):
            await run_update(manager, "BadNet", "wrong")
        assert manager.status.state == UpdateState.failed
        assert_hotspot_restored(runner)

    async def test_wifi_ssid_not_found_retries_then_succeeds(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path, seed_artifacts=True)
        original_run = runner.run
        connect_calls = {"count": 0}

        async def run_with_retry(args, *, timeout=30, env=None):
            joined = " ".join(args)
            if "connection up VibeSensor-Uplink" in joined:
                connect_calls["count"] += 1
                if connect_calls["count"] == 1:
                    return (10, "", "Error: No network with SSID 'TestNet' found.\n")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = run_with_retry  # type: ignore[assignment]
        with (
            patch("shutil.which", mock_which),
            patch("vibesensor.update.manager.asyncio.sleep", new=AsyncMock(return_value=None)),
            patch("vibesensor.release_fetcher.ServerReleaseFetcher") as mock_fetcher,
            patch("vibesensor.release_fetcher.ReleaseFetcherConfig"),
            patch("vibesensor._version.__version__", "2025.6.15"),
        ):
            mock_fetcher.return_value.check_update_available.return_value = None
            manager.start("TestNet", "pass123")
            await asyncio.wait_for(manager._task, timeout=10)

        assert manager.status.state == UpdateState.success
        assert connect_calls["count"] >= 2

    async def test_dns_not_ready_fails_with_clear_issue(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response("socket.getaddrinfo", 1, "", "Temporary failure in name resolution")
        with (
            patch_release_fetcher() as mock_fetcher,
            patch("vibesensor.update.manager.DNS_READY_MIN_WAIT_S", 0.05),
            patch("vibesensor.update.manager.DNS_RETRY_INTERVAL_S", 0.01),
        ):
            await run_update(manager)
            mock_fetcher.assert_not_called()
        assert manager.status.state == UpdateState.failed

    async def test_dns_probe_retries_then_update_continues(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path, seed_artifacts=True)
        original_run = runner.run
        probe_attempts = {"count": 0}

        async def run_with_dns_retry(args, *, timeout=30, env=None):
            if "socket.getaddrinfo" in " ".join(args):
                probe_attempts["count"] += 1
                if probe_attempts["count"] < 3:
                    return (1, "", "Temporary failure in name resolution")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = run_with_dns_retry  # type: ignore[assignment]
        with (
            patch_release_fetcher() as mock_fetcher,
            patch("vibesensor.update.manager.DNS_READY_MIN_WAIT_S", 0.2),
            patch("vibesensor.update.manager.DNS_RETRY_INTERVAL_S", 0.01),
        ):
            mock_fetcher.return_value.check_update_available.return_value = None
            await run_update(manager)

        assert manager.status.state == UpdateState.success
        assert probe_attempts["count"] >= 3

    async def test_secure_ssid_requires_password(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response("dev wifi list", 0, "Pim:WPA2\n")
        with patch("shutil.which", mock_which):
            await run_update(manager, "Pim", "")
        assert manager.status.state == UpdateState.failed

    async def test_password_is_applied_via_connection_modify(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path, seed_artifacts=True)
        with patch_release_fetcher() as mock_fetcher:
            mock_fetcher.return_value.check_update_available.return_value = None
            await run_update(manager, "Pim", "tomaat123")
        assert any(
            "connection modify VibeSensor-Uplink "
            "wifi-sec.key-mgmt wpa-psk wifi-sec.psk" in " ".join(call[0])
            for call in runner.calls
        )

    async def test_download_failure_still_restores_hotspot(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        with patch_release_fetcher(current_version="2025.6.14") as mock_fetcher:
            mock_release = make_mock_release(sha256="abc")
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = mock_release
            fetcher.download_wheel.side_effect = OSError("Network error")
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
        assert_hotspot_restored(runner)

    async def test_install_failure_triggers_rollback(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        runner.set_response("pip", 1, "", "ERROR: Could not install")
        (tmp_path / "rollback").mkdir()
        fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        wheel_content = _build_fake_wheel(fake_wheel, version="2025.6.15")
        wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()

        with patch_release_fetcher(current_version="2025.6.14") as mock_fetcher:
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = make_mock_release(sha256=wheel_sha256)
            fetcher.download_wheel.return_value = fake_wheel
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed

    async def test_snapshot_failure_aborts_before_install(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path, seed_artifacts=True)
        fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        wheel_content = _build_fake_wheel(fake_wheel, version="2025.6.15")
        wheel_sha256 = hashlib.sha256(wheel_content).hexdigest()

        with (
            patch_release_fetcher(current_version="2025.6.14") as mock_fetcher,
            patch(
                "vibesensor.update.installer.UpdateInstaller.snapshot_for_rollback",
                new=AsyncMock(return_value=False),
            ),
        ):
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = make_mock_release(sha256=wheel_sha256)
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
        with (
            patch("shutil.which", mock_which),
            patch("shutil.disk_usage", side_effect=OSError("statfs failed")),
        ):
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
        manager, runner, _ = setup_update_env(tmp_path)
        fake_wheel = tmp_path / "vibesensor-2025.6.15-py3-none-any.whl"
        fake_wheel.write_bytes(b"fake-wheel-content")

        with patch_release_fetcher(current_version="2025.6.14") as mock_fetcher:
            fetcher = mock_fetcher.return_value
            fetcher.check_update_available.return_value = make_mock_release(sha256="0" * 64)
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
        manager, _runner, _ = setup_update_env(tmp_path)
        with patch_release_fetcher() as mock_fetcher:
            mock_fetcher.return_value.check_update_available.return_value = None
            await run_update(manager, "TestNet", secret)
        serialized = str(manager.status.to_dict())
        assert secret not in serialized
        for line in manager.status.log_tail:
            assert secret not in line
        for issue in manager.status.issues:
            assert secret not in issue.message
            assert secret not in issue.detail

    async def test_stale_public_assets_detected_in_runtime(self, tmp_path) -> None:
        manager, _runner, repo = setup_update_env(tmp_path)
        seed_runtime_artifacts(repo, manager, valid=False)
        details = manager._runtime_details.collect()
        assert details["assets_verified"] is False

    async def test_timeout_handling(self, tmp_path) -> None:
        manager, runner, _ = setup_update_env(tmp_path)
        original_run = runner.run

        async def slow_run(args, *, timeout=30, env=None):
            if "connection up VibeSensor-Uplink" in " ".join(args):
                await asyncio.sleep(300)
                return (0, "", "")
            return await original_run(args, timeout=timeout, env=env)

        runner.run = slow_run  # type: ignore[assignment]
        with (
            patch("shutil.which", mock_which),
            patch("vibesensor.update.manager.UPDATE_TIMEOUT_S", 0.5),
            patch("vibesensor.update.manager.HOTSPOT_RESTORE_RETRIES", 1),
        ):
            manager.start("TestNet", "pass")
            await asyncio.wait_for(manager._task, timeout=3)
        assert manager.status.state == UpdateState.failed

    async def test_check_update_failure_fails_update(self, tmp_path) -> None:
        manager, _runner, _ = setup_update_env(tmp_path)
        with patch_release_fetcher(current_version="2025.6.14") as mock_fetcher:
            mock_fetcher.return_value.check_update_available.side_effect = RuntimeError(
                "API rate limit exceeded",
            )
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed

    @pytest.mark.parametrize("missing_tool", ["nmcli", "python3"])
    async def test_missing_tool_fails_gracefully(self, tmp_path, missing_tool: str) -> None:
        manager, _runner, _ = setup_update_env(tmp_path, sudo_ok=False, rollback=False)

        def which_without(name: str) -> str | None:
            return None if name == missing_tool else f"/usr/bin/{name}"

        with patch("shutil.which", which_without):
            await run_update(manager, "TestNet", "pass")
        assert manager.status.state == UpdateState.failed
