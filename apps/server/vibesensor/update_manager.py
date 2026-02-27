"""Background system-update manager.

Orchestrates: hotspot down → Wi-Fi uplink connect → download release →
install wheel → rollback on failure → hotspot restore.
All operations run as a background asyncio task so the API endpoint returns
immediately.  Job state is kept in memory and survives UI disconnects.
"""

from __future__ import annotations

import asyncio
import enum
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UPDATE_TIMEOUT_S = 600
"""Hard timeout for the entire update job (seconds)."""

GIT_OP_TIMEOUT_S = 120
"""Per-git-operation timeout (kept for legacy compat, unused in release flow)."""

REBUILD_OP_TIMEOUT_S = 300
"""Per-rebuild-operation timeout (kept for legacy compat, unused in release flow)."""

REBUILD_RETRY_DELAY_S = 3
"""Delay before retrying transient rebuild failures (legacy)."""

REINSTALL_OP_TIMEOUT_S = 180
"""Per-backend-reinstall timeout."""

DOWNLOAD_TIMEOUT_S = 300
"""Timeout for downloading a release wheel."""

ESP_FIRMWARE_REFRESH_TIMEOUT_S = 240
"""Per-online ESP firmware cache refresh timeout."""

NMCLI_TIMEOUT_S = 30
"""Per-nmcli-operation timeout."""

UPLINK_CONNECTION_NAME = "VibeSensor-Uplink"
UPLINK_CONNECT_WAIT_S = 30
UPLINK_FALLBACK_DNS = "1.1.1.1,1.0.0.1"
DNS_READY_MIN_WAIT_S = 10.0
DNS_RETRY_INTERVAL_S = 1.0
DNS_PROBE_HOST = "api.github.com"

DEFAULT_GIT_REMOTE = "https://github.com/Skamba/VibeSensor.git"
DEFAULT_GIT_BRANCH = "main"

HOTSPOT_RESTORE_RETRIES = 3
HOTSPOT_RESTORE_DELAY_S = 2

DEFAULT_ROLLBACK_DIR = "/var/lib/vibesensor/rollback"

UI_BUILD_METADATA_FILE = ".vibesensor-ui-build.json"
UPDATE_RESTART_UNIT = "vibesensor-post-update-restart"
UPDATE_SERVICE_NAME = "vibesensor.service"
SERVICE_ENV_DROPIN = "/etc/systemd/system/vibesensor.service.d/10-contracts-dir.conf"
SERVICE_CONTRACTS_DIR = "/opt/VibeSensor/libs/shared/contracts"
DEFAULT_REBUILD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
TRANSIENT_REBUILD_ERROR_MARKERS = (
    "eai_again",
    "enotfound",
    "econnreset",
    "etimedout",
    "network timeout",
    "temporary failure in name resolution",
    "registry.npmjs.org",
)


# ---------------------------------------------------------------------------
# Enums / Models
# ---------------------------------------------------------------------------


class UpdateState(enum.StrEnum):
    idle = "idle"
    running = "running"
    success = "success"
    failed = "failed"


class UpdatePhase(enum.StrEnum):
    idle = "idle"
    validating = "validating"
    stopping_hotspot = "stopping_hotspot"
    connecting_wifi = "connecting_wifi"
    checking = "checking"
    downloading = "downloading"
    installing = "installing"
    restoring_hotspot = "restoring_hotspot"
    done = "done"


@dataclass
class UpdateIssue:
    phase: str
    message: str
    detail: str = ""


@dataclass
class UpdateJobStatus:
    state: UpdateState = UpdateState.idle
    phase: UpdatePhase = UpdatePhase.idle
    started_at: float | None = None
    finished_at: float | None = None
    last_success_at: float | None = None
    ssid: str = ""
    issues: list[UpdateIssue] = field(default_factory=list)
    log_tail: list[str] = field(default_factory=list)
    exit_code: int | None = None
    runtime: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "phase": self.phase.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_success_at": self.last_success_at,
            "ssid": self.ssid,
            "issues": [
                {"phase": i.phase, "message": i.message, "detail": i.detail} for i in self.issues
            ],
            "log_tail": self.log_tail[-50:],
            "exit_code": self.exit_code,
            "runtime": self.runtime,
        }


def _hash_tree(root: Path, *, ignore_names: set[str]) -> str:
    if not root.exists():
        return ""
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root)
        if any(part in ignore_names for part in relative.parts):
            continue
        hasher.update(str(relative.as_posix()).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Command runner abstraction (for testability)
# ---------------------------------------------------------------------------


class CommandRunner:
    """Execute shell commands.  Override for testing."""

    async def run(
        self,
        args: list[str],
        *,
        timeout: float = 30,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        """Return (returncode, stdout, stderr)."""
        merged_env = {**os.environ, **(env or {})}
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=merged_env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return (
                proc.returncode or 0,
                stdout_bytes.decode(errors="replace"),
                stderr_bytes.decode(errors="replace"),
            )
        except TimeoutError:
            try:
                proc.kill()  # type: ignore[union-attr]
                await proc.wait()  # type: ignore[union-attr]
            except ProcessLookupError:
                pass
            return (124, "", "Command timed out")
        except FileNotFoundError:
            return (127, "", f"Command not found: {args[0]}")
        except OSError as exc:
            return (1, "", str(exc))


# ---------------------------------------------------------------------------
# sudo wrapper helpers
# ---------------------------------------------------------------------------

_WRAPPER_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vibesensor_update_sudo.sh"


def _sudo_prefix() -> list[str]:
    """Return the sudo prefix for privileged commands."""
    if os.geteuid() == 0:
        return []
    wrapper = _WRAPPER_SCRIPT
    if wrapper.is_file():
        return ["sudo", str(wrapper)]
    return ["sudo"]


# ---------------------------------------------------------------------------
# Diagnostics log parser
# ---------------------------------------------------------------------------


def parse_wifi_diagnostics(log_dir: str = "/var/log/wifi") -> list[UpdateIssue]:
    """Parse wifi diagnostic files into structured issues."""
    issues: list[UpdateIssue] = []
    log_path = Path(log_dir)
    if not log_path.is_dir():
        return issues

    summary = log_path / "summary.txt"
    if summary.is_file():
        try:
            text = summary.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("status=") and "FAILED" in line.upper():
                    issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot summary reports failure",
                            detail=line,
                        )
                    )
        except OSError:
            pass

    hotspot_log = log_path / "hotspot.log"
    if hotspot_log.is_file():
        try:
            text = hotspot_log.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            for line in lines[-100:]:
                lower = line.lower()
                if "error" in lower or "failed" in lower or "timeout" in lower:
                    sanitized = _sanitize_log_line(line)
                    issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot log issue",
                            detail=sanitized,
                        )
                    )
        except OSError:
            pass

    return issues


def _sanitize_log_line(line: str) -> str:
    """Remove potential credential leaks from log lines."""
    import re

    line = re.sub(r"(?i)(psk|password|secret|key)\s*[=:]\s*\S+", r"\1=***", line)
    return line[:500]


# ---------------------------------------------------------------------------
# UpdateManager
# ---------------------------------------------------------------------------


class UpdateManager:
    """Singleton-style manager for system update jobs.

    Holds the current job status in memory so the UI can poll
    ``/api/settings/update/status`` and see the latest state even after
    reconnecting.
    """

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        repo_path: str | None = None,
        git_remote: str | None = None,
        git_branch: str | None = None,
        ap_con_name: str = "VibeSensor-AP",
        wifi_ifname: str = "wlan0",
        rollback_dir: str | None = None,
    ) -> None:
        self._runner = runner or CommandRunner()
        self._repo_path = repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor")
        self._git_remote = git_remote or os.environ.get("VIBESENSOR_GIT_REMOTE", DEFAULT_GIT_REMOTE)
        self._git_branch = git_branch or os.environ.get("VIBESENSOR_GIT_BRANCH", DEFAULT_GIT_BRANCH)
        self._ap_con_name = ap_con_name
        self._wifi_ifname = wifi_ifname
        self._rollback_dir = Path(
            rollback_dir or os.environ.get("VIBESENSOR_ROLLBACK_DIR", DEFAULT_ROLLBACK_DIR)
        )
        self._status = UpdateJobStatus()
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()
        self._redact_secrets: set[str] = set()
        self._status.runtime = self._collect_runtime_details()

    # -- public API ----------------------------------------------------------

    @property
    def status(self) -> UpdateJobStatus:
        return self._status

    def start(self, ssid: str, password: str) -> None:
        """Start an update job.  Raises ValueError on bad input, RuntimeError if busy."""
        ssid = ssid.strip()
        if not ssid or len(ssid) > 64:
            raise ValueError("SSID must be 1-64 characters")
        if password and len(password) > 128:
            raise ValueError("Password must be at most 128 characters")
        if self._task is not None and not self._task.done():
            raise RuntimeError("Update already in progress")

        # Reset
        self._cancel_event.clear()
        previous_runtime = dict(self._status.runtime)
        self._status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.validating,
            started_at=time.time(),
            ssid=ssid,
            last_success_at=self._status.last_success_at,
            runtime=previous_runtime,
        )
        # Track password for log redaction, launch background task
        self._redact_secrets = {password} if password else set()
        self._task = asyncio.get_running_loop().create_task(
            self._run_update(ssid, password),
            name="system-update",
        )

    def cancel(self) -> bool:
        """Request cancellation.  Returns True if a job was running."""
        if self._task is None or self._task.done():
            return False
        self._cancel_event.set()
        return True

    # -- internals -----------------------------------------------------------

    def _redact(self, text: str) -> str:
        """Replace any tracked secrets with ***."""
        for secret in self._redact_secrets:
            if secret:
                text = text.replace(secret, "***")
        return text

    def _log(self, msg: str) -> None:
        sanitized = self._redact(_sanitize_log_line(msg))
        self._status.log_tail.append(sanitized)
        if len(self._status.log_tail) > 200:
            self._status.log_tail = self._status.log_tail[-100:]
        LOGGER.debug("update event recorded")

    def _redacted_args_for_log(self, args: list[str]) -> list[str]:
        """Return command args with sensitive values replaced by *** for safe logging."""
        redacted: list[str] = []
        hide_next = False
        sensitive_keys = {
            "password",
            "psk",
            "secret",
            "key",
            "802-11-wireless-security.psk",
        }
        for raw_arg in args:
            arg = str(raw_arg)
            lowered = arg.lower()
            if hide_next:
                redacted.append("***")
                hide_next = False
                continue
            if lowered in sensitive_keys:
                redacted.append(arg)
                hide_next = True
                continue
            if any(secret and arg == secret for secret in self._redact_secrets):
                redacted.append("***")
                continue
            redacted.append(arg)
        return redacted

    def _add_issue(self, phase: str, message: str, detail: str = "") -> None:
        self._status.issues.append(
            UpdateIssue(
                phase=phase,
                message=self._redact(message),
                detail=self._redact(_sanitize_log_line(detail)),
            )
        )

    @staticmethod
    def _ssid_security_modes(scan_output: str, ssid: str) -> set[str]:
        modes: set[str] = set()
        target = ssid.strip()
        if not target:
            return modes
        for line in scan_output.splitlines():
            raw = line.strip()
            if not raw or ":" not in raw:
                continue
            candidate_ssid, security = raw.split(":", 1)
            if candidate_ssid.strip() != target:
                continue
            sec = security.strip()
            if sec and sec != "--":
                modes.add(sec)
        return modes

    async def _run_cmd(
        self,
        args: list[str],
        *,
        timeout: float = NMCLI_TIMEOUT_S,
        env: dict[str, str] | None = None,
        phase: str = "",
        sudo: bool = False,
    ) -> tuple[int, str, str]:
        if sudo:
            args = [*_sudo_prefix(), *args]
        cmd_for_log = " ".join(self._redacted_args_for_log(args)) if args else "<empty>"
        if len(cmd_for_log) > 500:
            cmd_for_log = f"{cmd_for_log[:497]}..."
        self._log(f"[{phase}] $ {cmd_for_log}")
        rc, stdout, stderr = await self._runner.run(args, timeout=timeout, env=env)
        if stdout.strip():
            self._log(f"[{phase}] stdout: {_sanitize_log_line(stdout.strip()[:500])}")
        if stderr.strip():
            self._log(f"[{phase}] stderr: {_sanitize_log_line(stderr.strip()[:500])}")
        if rc != 0:
            self._log(f"[{phase}] exit code: {rc}")
        return rc, stdout, stderr

    async def _wait_for_dns_ready(self) -> bool:
        """Wait for uplink DNS resolution before online update operations."""
        self._log(
            f"Validating uplink internet/DNS readiness for at least {int(DNS_READY_MIN_WAIT_S)}s..."
        )
        probe_cmd = [
            "python3",
            "-c",
            (
                "import socket; "
                f"socket.getaddrinfo('{DNS_PROBE_HOST}', 443, proto=socket.IPPROTO_TCP)"
            ),
        ]
        deadline = time.monotonic() + DNS_READY_MIN_WAIT_S
        last_error = ""
        attempt = 0

        while True:
            attempt += 1
            rc, stdout, stderr = await self._run_cmd(
                probe_cmd,
                phase="connecting_wifi",
                timeout=5,
                sudo=False,
            )
            if rc == 0:
                self._log(f"DNS probe succeeded on attempt {attempt}")
                return True

            last_error = (stderr or stdout or f"exit {rc}").strip()
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(DNS_RETRY_INTERVAL_S)

        self._add_issue(
            "connecting_wifi",
            "Connected to Wi-Fi, but internet/DNS is not ready",
            (
                f"Waited at least {int(DNS_READY_MIN_WAIT_S)} seconds for DNS resolution "
                f"({DNS_PROBE_HOST}) before starting the updater. "
                f"Last probe error: {last_error or 'unknown'}"
            ),
        )
        return False

    async def _restore_hotspot(self) -> bool:
        """Best-effort hotspot restore with retries.  Returns True if successful."""
        self._status.phase = UpdatePhase.restoring_hotspot
        self._log("Restoring hotspot...")

        # Clean up temporary uplink connection
        await self._run_cmd(
            ["nmcli", "connection", "down", UPLINK_CONNECTION_NAME],
            phase="restore",
            sudo=True,
        )
        await self._run_cmd(
            ["nmcli", "connection", "delete", UPLINK_CONNECTION_NAME],
            phase="restore",
            sudo=True,
        )

        for attempt in range(1, HOTSPOT_RESTORE_RETRIES + 1):
            rc, _, _ = await self._run_cmd(
                ["nmcli", "connection", "up", self._ap_con_name],
                phase="restore",
                sudo=True,
            )
            if rc == 0:
                self._log(f"Hotspot restored on attempt {attempt}")
                return True
            self._log(f"Hotspot restore attempt {attempt} failed (rc={rc})")
            if attempt < HOTSPOT_RESTORE_RETRIES:
                await asyncio.sleep(HOTSPOT_RESTORE_DELAY_S)

        self._add_issue("restoring_hotspot", "Failed to restore hotspot after retries")
        return False

    async def _run_update(self, ssid: str, password: str) -> None:
        """Main update coroutine.  Always restores hotspot on exit."""
        try:
            await asyncio.wait_for(
                self._run_update_inner(ssid, password),
                timeout=UPDATE_TIMEOUT_S,
            )
        except TimeoutError:
            self._add_issue("timeout", f"Update timed out after {UPDATE_TIMEOUT_S}s")
            self._log(f"Update timed out after {UPDATE_TIMEOUT_S}s")
            self._status.state = UpdateState.failed
        except asyncio.CancelledError:
            self._add_issue("cancelled", "Update was cancelled")
            self._log("Update cancelled")
            self._status.state = UpdateState.failed
        except Exception as exc:
            self._add_issue("unexpected", f"Unexpected error: {exc}")
            LOGGER.exception("update: unexpected error")
            self._status.state = UpdateState.failed
        finally:
            # Always try to restore the hotspot
            if self._status.phase not in (UpdatePhase.idle, UpdatePhase.done):
                await self._restore_hotspot()
            self._status.finished_at = time.time()
            if self._status.state == UpdateState.running:
                # If we reach here still "running", something went wrong
                self._status.state = UpdateState.failed
            if self._status.state != UpdateState.failed:
                self._status.phase = UpdatePhase.done
            # Clear secrets from memory
            self._redact_secrets.clear()
            self._status.runtime = self._collect_runtime_details()

            # Parse diagnostics
            try:
                diag_issues = await asyncio.to_thread(parse_wifi_diagnostics)
                self._status.issues.extend(diag_issues)
            except Exception:
                pass

    async def _run_update_inner(self, ssid: str, password: str) -> None:
        # --- Phase: Validate ---
        self._status.phase = UpdatePhase.validating
        self._log(f"Starting update with SSID: {ssid}")

        # Check required tools (git and npm no longer needed)
        for tool in ("nmcli", "python3"):
            if not shutil.which(tool):
                self._add_issue("validating", f"Required tool not found: {tool}")
                self._status.state = UpdateState.failed
                return

        # Check sudo / privileges
        if os.geteuid() != 0:
            rc, _, _ = await self._run_cmd(["sudo", "-n", "true"], phase="validating", timeout=5)
            if rc != 0:
                self._add_issue(
                    "validating",
                    "Insufficient privileges",
                    "Cannot run sudo non-interactively. "
                    "In dev/Docker environments, hotspot management is not available.",
                )
                self._status.state = UpdateState.failed
                return

        if self._cancel_event.is_set():
            return

        # --- Phase: Stop hotspot ---
        self._status.phase = UpdatePhase.stopping_hotspot
        self._log("Stopping hotspot...")

        rc, _, _ = await self._run_cmd(
            ["nmcli", "connection", "down", self._ap_con_name],
            phase="stopping_hotspot",
            sudo=True,
        )
        if rc != 0:
            self._log("Hotspot down returned non-zero; may already be inactive")

        if self._cancel_event.is_set():
            return

        # --- Phase: Connect to Wi-Fi ---
        self._status.phase = UpdatePhase.connecting_wifi
        self._log(f"Connecting to Wi-Fi network: {ssid}")

        if not password:
            rc, stdout, _ = await self._run_cmd(
                [
                    "nmcli",
                    "-t",
                    "-f",
                    "SSID,SECURITY",
                    "dev",
                    "wifi",
                    "list",
                    "ifname",
                    self._wifi_ifname,
                    "--rescan",
                    "yes",
                ],
                phase="connecting_wifi",
                timeout=NMCLI_TIMEOUT_S,
                sudo=True,
            )
            if rc == 0:
                security_modes = self._ssid_security_modes(stdout, ssid)
                if security_modes:
                    self._add_issue(
                        "connecting_wifi",
                        "Wi-Fi password required for secured network",
                        f"SSID '{ssid}' advertises security: {', '.join(sorted(security_modes))}",
                    )
                    self._status.state = UpdateState.failed
                    return

        # Clean up any previous uplink
        rc, stdout, _ = await self._run_cmd(
            ["nmcli", "-t", "-f", "UUID,NAME", "connection", "show"],
            phase="connecting_wifi",
            sudo=True,
        )
        existing_uplink_uuids: list[str] = []
        if rc == 0 and stdout:
            for line in stdout.splitlines():
                if not line:
                    continue
                uuid, _, name = line.partition(":")
                if name == UPLINK_CONNECTION_NAME and uuid:
                    existing_uplink_uuids.append(uuid)
        for uuid in existing_uplink_uuids:
            await self._run_cmd(
                ["nmcli", "connection", "delete", "uuid", uuid],
                phase="connecting_wifi",
                sudo=True,
            )

        # Create uplink connection
        add_cmd = [
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            self._wifi_ifname,
            "con-name",
            UPLINK_CONNECTION_NAME,
            "autoconnect",
            "no",
            "ssid",
            ssid,
        ]
        if password:
            add_cmd.extend(["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password])

        rc, _, stderr = await self._run_cmd(
            add_cmd,
            phase="connecting_wifi",
            sudo=True,
        )
        if rc != 0:
            self._add_issue("connecting_wifi", "Failed to create uplink connection", stderr)
            self._status.state = UpdateState.failed
            return

        rc, _, stderr = await self._run_cmd(
            [
                "nmcli",
                "connection",
                "modify",
                UPLINK_CONNECTION_NAME,
                "autoconnect",
                "no",
                "ipv4.method",
                "auto",
                "ipv4.ignore-auto-dns",
                "yes",
                "ipv4.dns",
                UPLINK_FALLBACK_DNS,
                "ipv6.method",
                "ignore",
            ],
            phase="connecting_wifi",
            sudo=True,
        )

        if rc != 0:
            self._add_issue("connecting_wifi", "Failed to configure uplink", stderr)
            self._status.state = UpdateState.failed
            return

        rc = 1
        stderr = ""
        for attempt in range(1, 4):
            rc, _, stderr = await self._run_cmd(
                [
                    "nmcli",
                    "--wait",
                    str(UPLINK_CONNECT_WAIT_S),
                    "connection",
                    "up",
                    UPLINK_CONNECTION_NAME,
                ],
                phase="connecting_wifi",
                sudo=True,
                timeout=float(UPLINK_CONNECT_WAIT_S + 10),
            )
            if rc != 0:
                if "No network with SSID" not in (stderr or ""):
                    break
                self._log(
                    f"SSID '{ssid}' not found on connect attempt {attempt}; rescanning and retrying"
                )
                await self._run_cmd(
                    [
                        "nmcli",
                        "-t",
                        "-f",
                        "SSID,SIGNAL,CHAN,FREQ",
                        "dev",
                        "wifi",
                        "list",
                        "ifname",
                        self._wifi_ifname,
                        "--rescan",
                        "yes",
                    ],
                    phase="connecting_wifi",
                    timeout=NMCLI_TIMEOUT_S,
                    sudo=True,
                )
                await asyncio.sleep(2.0)
                continue
            break

        if rc != 0:
            self._add_issue("connecting_wifi", f"Failed to connect to Wi-Fi '{ssid}'", stderr)
            self._status.state = UpdateState.failed
            return

        self._log(f"Wi-Fi connected successfully (client DNS fallback={UPLINK_FALLBACK_DNS})")

        if self._cancel_event.is_set():
            return

        if not await self._wait_for_dns_ready():
            self._status.state = UpdateState.failed
            return

        # --- Phase: Check for updates ---
        self._status.phase = UpdatePhase.checking
        self._log("Checking for available updates...")

        from vibesensor import __version__ as current_version
        from vibesensor.release_fetcher import ReleaseFetcherConfig, ServerReleaseFetcher

        fetcher_config = ReleaseFetcherConfig(
            rollback_dir=str(self._rollback_dir),
        )
        fetcher = ServerReleaseFetcher(fetcher_config)

        try:
            release = await asyncio.to_thread(fetcher.check_update_available, current_version)
        except Exception as exc:
            self._add_issue("checking", f"Failed to check for updates: {exc}")
            self._status.state = UpdateState.failed
            return

        if release is None:
            self._log(f"Already up-to-date (version={current_version})")
            # Still refresh ESP firmware cache
            await self._refresh_esp_firmware()

            if self._cancel_event.is_set():
                return

            restored = await self._restore_hotspot()
            if not restored:
                self._status.state = UpdateState.failed
                return
            self._status.state = UpdateState.success
            self._status.phase = UpdatePhase.done
            self._status.last_success_at = time.time()
            self._status.exit_code = 0
            self._log("No server update needed; ESP firmware checked")
            return

        self._log(f"Update available: {current_version} → {release.version}")

        if self._cancel_event.is_set():
            return

        # --- Phase: Download ---
        self._status.phase = UpdatePhase.downloading
        self._log(f"Downloading release {release.tag}...")

        import tempfile

        staging_dir = Path(tempfile.mkdtemp(prefix="vibesensor-update-"))
        try:
            wheel_path = await asyncio.to_thread(fetcher.download_wheel, release, staging_dir)
        except Exception as exc:
            self._add_issue("downloading", f"Failed to download release: {exc}")
            self._status.state = UpdateState.failed
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return

        self._log(f"Downloaded {wheel_path.name} (sha256={release.sha256})")

        # Also refresh ESP firmware
        await self._refresh_esp_firmware()

        if self._cancel_event.is_set():
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return

        # --- Phase: Install ---
        self._status.phase = UpdatePhase.installing
        self._log("Installing update...")

        # Snapshot current version for rollback
        rollback_ok = await self._snapshot_for_rollback()
        if not rollback_ok:
            self._log("WARNING: Could not create rollback snapshot; proceeding anyway")

        repo = Path(self._repo_path)
        venv_python = self._reinstall_python_executable(repo)
        if not Path(venv_python).is_file():
            # Fall back to system python in venv
            venv_python = str(
                Path(self._repo_path) / "apps" / "server" / ".venv" / "bin" / "python3"
            )

        # Install the new wheel
        install_cmd = [
            venv_python,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            str(wheel_path),
        ]
        rc, _, stderr = await self._run_cmd(
            install_cmd,
            phase="installing",
            timeout=REINSTALL_OP_TIMEOUT_S,
            sudo=False,
        )
        if rc != 0:
            self._add_issue("installing", f"Wheel install failed (exit {rc})", stderr)
            self._log("Attempting rollback...")
            await self._rollback()
            self._status.state = UpdateState.failed
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return

        self._log(f"Installed vibesensor {release.version}")

        # Verify the installed package can be imported
        verify_cmd = [
            venv_python,
            "-c",
            "from vibesensor import __version__; print(__version__)",
        ]
        rc, stdout, stderr = await self._run_cmd(
            verify_cmd,
            phase="installing",
            timeout=30,
            sudo=False,
        )
        if rc != 0:
            self._add_issue(
                "installing",
                f"Post-install verification failed (exit {rc})",
                stderr,
            )
            self._log("Attempting rollback...")
            await self._rollback()
            self._status.state = UpdateState.failed
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return

        installed_version = stdout.strip()
        self._log(f"Verified installed version: {installed_version}")

        # Clean up staging
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

        runtime_details = self._collect_runtime_details()
        self._status.runtime = runtime_details

        if self._cancel_event.is_set():
            return

        # --- Phase: Restore hotspot ---
        restored = await self._restore_hotspot()
        if not restored:
            self._status.state = UpdateState.failed
            return

        # --- Done ---
        self._status.state = UpdateState.success
        self._status.phase = UpdatePhase.done
        self._status.last_success_at = time.time()
        self._status.exit_code = 0
        self._log("Update completed successfully")
        await self._ensure_service_contracts_env()
        if not await self._schedule_service_restart():
            self._add_issue(
                "done",
                "Backend restart was not scheduled automatically",
                f"Run 'sudo systemctl restart {UPDATE_SERVICE_NAME}' manually",
            )
            self._log("Automatic backend restart scheduling failed")

    async def _refresh_esp_firmware(self) -> None:
        """Refresh the ESP firmware cache.  Non-fatal on failure."""
        self._log("Refreshing ESP firmware cache...")
        repo = Path(self._repo_path)
        venv_python = self._reinstall_python_executable(repo)
        refresh_exe = str(Path(venv_python).with_name("vibesensor-fw-refresh"))
        # Fall back to module invocation if the entry point doesn't exist
        if not Path(refresh_exe).is_file():
            refresh_cmd = [venv_python, "-m", "vibesensor.firmware_cache"]
        else:
            refresh_cmd = [
                refresh_exe,
                "--cache-dir",
                "/var/lib/vibesensor/firmware",
            ]
        rc, _, stderr = await self._run_cmd(
            refresh_cmd,
            phase="downloading",
            timeout=ESP_FIRMWARE_REFRESH_TIMEOUT_S,
            sudo=False,
        )
        if rc != 0:
            self._add_issue(
                "downloading",
                f"ESP firmware cache refresh failed (exit {rc})",
                stderr,
            )
            self._log("ESP firmware refresh failed; continuing with existing cache")
        else:
            self._log("ESP firmware cache refresh completed successfully")

    async def _snapshot_for_rollback(self) -> bool:
        """Save the current wheel to the rollback directory.

        Returns True on success, False on failure (non-fatal).
        """
        self._rollback_dir.mkdir(parents=True, exist_ok=True)
        repo = Path(self._repo_path)
        venv_python = self._reinstall_python_executable(repo)

        # Use pip to download the currently installed version into rollback dir
        from vibesensor import __version__ as current_version

        self._log(f"Creating rollback snapshot (version={current_version})")

        # Clear old rollback wheels
        for old_whl in self._rollback_dir.glob("vibesensor-*.whl"):
            old_whl.unlink()

        # pip download the installed package to rollback dir
        rc, _, stderr = await self._run_cmd(
            [
                venv_python,
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--no-build-isolation",
                "-d",
                str(self._rollback_dir),
                f"vibesensor=={current_version}",
            ],
            phase="installing",
            timeout=60,
            sudo=False,
        )
        if rc != 0:
            # Fallback: just record the version number
            self._log(f"pip download for rollback failed (exit {rc}): {stderr}")
            meta_path = self._rollback_dir / "rollback_version.txt"
            meta_path.write_text(current_version, encoding="utf-8")
            return False

        self._log("Rollback snapshot created successfully")
        return True

    async def _rollback(self) -> bool:
        """Attempt to restore the previous version from rollback dir.

        Returns True if rollback succeeded.
        """
        self._log("Rolling back to previous version...")
        rollback_wheels = list(self._rollback_dir.glob("vibesensor-*.whl"))
        if not rollback_wheels:
            self._add_issue("installing", "No rollback wheel available")
            return False

        repo = Path(self._repo_path)
        venv_python = self._reinstall_python_executable(repo)
        wheel = rollback_wheels[0]

        rc, _, stderr = await self._run_cmd(
            [
                venv_python,
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(wheel),
            ],
            phase="installing",
            timeout=REINSTALL_OP_TIMEOUT_S,
            sudo=False,
        )
        if rc != 0:
            self._add_issue(
                "installing",
                f"Rollback install failed (exit {rc})",
                stderr,
            )
            return False

        self._log(f"Rolled back to {wheel.name}")
        return True

    @staticmethod
    def _backend_install_target(repo: Path) -> Path:
        server_pkg = repo / "apps" / "server"
        if (server_pkg / "pyproject.toml").is_file():
            return server_pkg
        return repo

    @staticmethod
    def _is_transient_rebuild_failure(stderr: str) -> bool:
        normalized = stderr.lower()
        return any(marker in normalized for marker in TRANSIENT_REBUILD_ERROR_MARKERS)

    async def _ensure_backend_venv(self, repo: Path) -> str | None:
        venv_python = Path(self._reinstall_python_executable(repo))
        venv_dir = venv_python.parent.parent
        if not self._is_reinstall_venv_ready(repo):
            self._log("Backend virtualenv missing or incomplete; creating it")
            rc, _, stderr = await self._run_cmd(
                ["python3", "-m", "venv", str(venv_dir)],
                phase="updating",
                timeout=120,
                sudo=True,
            )
            if rc != 0:
                self._add_issue(
                    "updating",
                    f"Backend virtualenv creation failed (exit {rc})",
                    stderr,
                )
                return None

        # Verify this interpreter is an actual virtualenv interpreter. A broken
        # symlink to system python triggers PEP 668 externally-managed failures.
        rc, _, stderr = await self._run_cmd(
            [
                str(venv_python),
                "-c",
                "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)",
            ],
            phase="updating",
            timeout=30,
            sudo=True,
        )
        if rc != 0:
            self._add_issue(
                "updating",
                "Backend virtualenv is invalid",
                stderr or f"{venv_python} is not running inside a virtualenv",
            )
            return None

        rc, _, stderr = await self._run_cmd(
            [str(venv_python), "-m", "pip", "--version"],
            phase="updating",
            timeout=30,
            sudo=True,
        )
        if rc == 0:
            return str(venv_python)

        self._log("pip missing in backend virtualenv; bootstrapping via ensurepip")
        rc, _, stderr = await self._run_cmd(
            [str(venv_python), "-m", "ensurepip", "--upgrade"],
            phase="updating",
            timeout=60,
            sudo=True,
        )
        if rc != 0:
            self._add_issue(
                "updating",
                f"Backend virtualenv pip bootstrap failed (exit {rc})",
                stderr,
            )
            return None

        rc, _, stderr = await self._run_cmd(
            [str(venv_python), "-m", "pip", "--version"],
            phase="updating",
            timeout=30,
            sudo=True,
        )
        if rc != 0:
            self._add_issue(
                "updating",
                f"Backend virtualenv pip verification failed (exit {rc})",
                stderr,
            )
            return None
        return str(venv_python)

    @staticmethod
    def _reinstall_venv_python_path(repo: Path) -> Path:
        return repo / "apps" / "server" / ".venv" / "bin" / "python3"

    @staticmethod
    def _reinstall_venv_config_path(repo: Path) -> Path:
        return repo / "apps" / "server" / ".venv" / "pyvenv.cfg"

    @classmethod
    def _is_reinstall_venv_ready(cls, repo: Path) -> bool:
        venv_python = cls._reinstall_venv_python_path(repo)
        if not (venv_python.is_file() and os.access(venv_python, os.X_OK)):
            return False
        return cls._reinstall_venv_config_path(repo).is_file()

    @staticmethod
    def _reinstall_python_executable(repo: Path) -> str:
        return str(UpdateManager._reinstall_venv_python_path(repo))

    async def _schedule_service_restart(self) -> bool:
        # Prefer a delayed transient unit so this update task can finish cleanly
        # before restarting the currently running service process.
        restart_attempts = [
            [
                "systemd-run",
                "--unit",
                UPDATE_RESTART_UNIT,
                "--on-active=2s",
                "systemctl",
                "restart",
                UPDATE_SERVICE_NAME,
            ],
            ["systemctl", "restart", UPDATE_SERVICE_NAME],
        ]
        for command in restart_attempts:
            rc, _, _ = await self._run_cmd(command, phase="done", timeout=30, sudo=True)
            if rc == 0:
                self._log("Scheduled backend service restart")
                return True
        return False

    async def _ensure_service_contracts_env(self) -> None:
        contracts_dir = Path(SERVICE_CONTRACTS_DIR)
        if not contracts_dir.is_dir():
            return

        dropin_path = Path(SERVICE_ENV_DROPIN)
        dropin_body = f"[Service]\\nEnvironment=VIBESENSOR_CONTRACTS_DIR={contracts_dir}\\n"
        escaped_body = dropin_body.replace("\\", "\\\\").replace("'", "\\'")
        script = (
            "from pathlib import Path; "
            f"p=Path('{dropin_path}'); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"content='{escaped_body}'; "
            "changed=(not p.exists()) or (p.read_text(encoding='utf-8')!=content); "
            "p.write_text(content, encoding='utf-8'); "
            "print('changed' if changed else 'unchanged')"
        )

        rc, stdout, stderr = await self._run_cmd(
            ["python3", "-c", script],
            phase="done",
            timeout=15,
            sudo=True,
        )
        if rc != 0:
            self._add_issue(
                "done",
                "Failed to configure contracts environment for service",
                stderr,
            )
            return

        if "changed" in (stdout or ""):
            rc, _, stderr = await self._run_cmd(
                ["systemctl", "daemon-reload"],
                phase="done",
                timeout=15,
                sudo=True,
            )
            if rc != 0:
                self._add_issue(
                    "done",
                    "Failed to reload systemd after contracts environment update",
                    stderr,
                )
                return
            self._log("Updated systemd drop-in for shared contracts directory")

    def _collect_runtime_details(self) -> dict[str, Any]:
        repo = Path(self._repo_path)
        ui_root = repo / "apps" / "ui"
        public_root = repo / "apps" / "server" / "public"
        metadata_path = public_root / UI_BUILD_METADATA_FILE

        # Get installed version
        try:
            from vibesensor import __version__

            version = __version__
        except Exception:
            version = "unknown"

        commit = ""
        if (repo / ".git").exists():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "HEAD"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode == 0:
                    commit = proc.stdout.strip()
            except OSError:
                pass

        # Check for packaged static assets (wheel-based install)
        packaged_static = Path(__file__).resolve().parent / "static"
        has_packaged_static = (packaged_static / "index.html").exists()

        ui_source_hash = _hash_tree(
            ui_root,
            ignore_names={"node_modules", "dist", ".git", ".npm-ci-lock.sha256"},
        )
        public_assets_hash = _hash_tree(public_root, ignore_names={UI_BUILD_METADATA_FILE})

        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = {}

        public_build_source_hash = str(metadata.get("ui_source_hash") or "")
        public_build_assets_hash = str(metadata.get("public_assets_hash") or "")
        public_build_commit = str(metadata.get("git_commit") or "")

        # Assets are verified if either packaged static assets exist (wheel)
        # or the legacy public/ dir matches the source hashes.
        assets_verified = has_packaged_static or (
            bool(ui_source_hash)
            and bool(public_assets_hash)
            and bool(public_build_source_hash)
            and bool(public_build_assets_hash)
            and ui_source_hash == public_build_source_hash
            and public_assets_hash == public_build_assets_hash
        )

        return {
            "version": version,
            "commit": commit,
            "ui_source_hash": ui_source_hash,
            "public_assets_hash": public_assets_hash,
            "public_build_source_hash": public_build_source_hash,
            "public_build_commit": public_build_commit,
            "assets_verified": assets_verified,
            "has_packaged_static": has_packaged_static,
        }

    def _bootstrap_runtime_metadata_if_missing(self) -> None:
        metadata_path = (
            Path(self._repo_path) / "apps" / "server" / "public" / UI_BUILD_METADATA_FILE
        )
        if metadata_path.exists():
            return
        details = self._collect_runtime_details()
        if not details.get("ui_source_hash") or not details.get("public_assets_hash"):
            return
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            metadata_path.write_text(
                json.dumps(
                    {
                        "ui_source_hash": details["ui_source_hash"],
                        "public_assets_hash": details["public_assets_hash"],
                        "git_commit": details["commit"],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            self._log("Generated runtime UI build metadata for update verification")
        except OSError as exc:
            self._log(f"Failed to write runtime metadata: {exc}")
