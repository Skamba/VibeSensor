"""Background system-update manager.

Orchestrates: hotspot down → Wi-Fi uplink connect → git pull → hotspot restore.
All operations run as a background asyncio task so the API endpoint returns
immediately.  Job state is kept in memory and survives UI disconnects.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UPDATE_TIMEOUT_S = 300
"""Hard timeout for the entire update job (seconds)."""

GIT_OP_TIMEOUT_S = 120
"""Per-git-operation timeout."""

NMCLI_TIMEOUT_S = 30
"""Per-nmcli-operation timeout."""

UPLINK_CONNECTION_NAME = "VibeSensor-Uplink"

DEFAULT_GIT_REMOTE = "https://github.com/Skamba/VibeSensor.git"
DEFAULT_GIT_BRANCH = "main"

HOTSPOT_RESTORE_RETRIES = 3
HOTSPOT_RESTORE_DELAY_S = 2


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
    updating = "updating"
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
        }


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
    ) -> None:
        self._runner = runner or CommandRunner()
        self._repo_path = repo_path or os.environ.get("VIBESENSOR_REPO_PATH", "/opt/VibeSensor")
        self._git_remote = git_remote or os.environ.get("VIBESENSOR_GIT_REMOTE", DEFAULT_GIT_REMOTE)
        self._git_branch = git_branch or os.environ.get("VIBESENSOR_GIT_BRANCH", DEFAULT_GIT_BRANCH)
        self._ap_con_name = ap_con_name
        self._wifi_ifname = wifi_ifname
        self._status = UpdateJobStatus()
        self._task: asyncio.Task[None] | None = None
        self._cancel_event = asyncio.Event()
        self._redact_secrets: set[str] = set()

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
        self._status = UpdateJobStatus(
            state=UpdateState.running,
            phase=UpdatePhase.validating,
            started_at=time.time(),
            ssid=ssid,
            last_success_at=self._status.last_success_at,
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
        LOGGER.info("update: %s", sanitized)

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
        cmd = args[0] if args else "<empty>"
        self._log(f"[{phase}] $ {cmd} [args redacted]")
        rc, stdout, stderr = await self._runner.run(args, timeout=timeout, env=env)
        if stdout.strip():
            self._log(f"[{phase}] stdout: {_sanitize_log_line(stdout.strip()[:500])}")
        if stderr.strip():
            self._log(f"[{phase}] stderr: {_sanitize_log_line(stderr.strip()[:500])}")
        if rc != 0:
            self._log(f"[{phase}] exit code: {rc}")
        return rc, stdout, stderr

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

        # Check required tools
        for tool in ("nmcli", "git"):
            if not shutil.which(tool):
                self._add_issue("validating", f"Required tool not found: {tool}")
                self._status.state = UpdateState.failed
                return

        # Check sudo / privileges
        if os.geteuid() != 0:
            # Check if we can sudo
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

        # Clean up any previous uplink
        await self._run_cmd(
            ["nmcli", "connection", "delete", UPLINK_CONNECTION_NAME],
            phase="connecting_wifi",
            sudo=True,
        )

        # Create uplink connection
        rc, _, stderr = await self._run_cmd(
            [
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
            ],
            phase="connecting_wifi",
            sudo=True,
        )
        if rc != 0:
            self._add_issue("connecting_wifi", "Failed to create uplink connection", stderr)
            self._status.state = UpdateState.failed
            return

        # Write credentials to a temporary file (never log them)
        cred_file = None
        try:
            if password:
                cred_file = tempfile.NamedTemporaryFile(
                    mode="w", prefix="vs_uplink_", suffix=".tmp", delete=False
                )
                cred_file.write(password)
                cred_file.close()
                os.chmod(cred_file.name, 0o600)

                rc, _, stderr = await self._run_cmd(
                    [
                        "nmcli",
                        "connection",
                        "modify",
                        UPLINK_CONNECTION_NAME,
                        "802-11-wireless-security.key-mgmt",
                        "wpa-psk",
                        "802-11-wireless-security.psk-flags",
                        "0",
                        "802-11-wireless-security.psk",
                        password,
                        "ipv4.method",
                        "auto",
                        "ipv6.method",
                        "ignore",
                    ],
                    phase="connecting_wifi",
                    sudo=True,
                )
            else:
                rc, _, stderr = await self._run_cmd(
                    [
                        "nmcli",
                        "connection",
                        "modify",
                        UPLINK_CONNECTION_NAME,
                        "ipv4.method",
                        "auto",
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
        finally:
            if cred_file and os.path.exists(cred_file.name):
                try:
                    os.unlink(cred_file.name)
                except OSError:
                    pass

        # Bring up the uplink
        rc, _, stderr = await self._run_cmd(
            ["nmcli", "connection", "up", UPLINK_CONNECTION_NAME, "--wait", "15"],
            phase="connecting_wifi",
            sudo=True,
            timeout=30,
        )
        if rc != 0:
            self._add_issue("connecting_wifi", f"Failed to connect to Wi-Fi '{ssid}'", stderr)
            self._status.state = UpdateState.failed
            return

        self._log("Wi-Fi connected successfully")

        if self._cancel_event.is_set():
            return

        # --- Phase: Update from git ---
        self._status.phase = UpdatePhase.updating
        self._log(f"Updating from {self._git_remote} ({self._git_branch})")

        repo = Path(self._repo_path)
        if not (repo / ".git").is_dir():
            self._add_issue(
                "updating",
                f"Repo path {self._repo_path} is not a git checkout",
            )
            self._status.state = UpdateState.failed
            return

        git_ok = True
        git_base = ["git", "-C", self._repo_path]
        for git_args, desc in [
            ([*git_base, "remote", "set-url", "origin", self._git_remote], "set remote"),
            ([*git_base, "fetch", "--depth", "1", "origin", self._git_branch], "fetch"),
            ([*git_base, "checkout", self._git_branch], "checkout"),
            ([*git_base, "pull", "--ff-only", "origin", self._git_branch], "pull"),
        ]:
            if self._cancel_event.is_set():
                return
            rc, _, stderr = await self._run_cmd(
                git_args,
                phase="updating",
                timeout=GIT_OP_TIMEOUT_S,
                sudo=True,
            )
            if rc != 0:
                self._add_issue("updating", f"Git {desc} failed (exit {rc})", stderr)
                git_ok = False
                break

        if not git_ok:
            self._status.state = UpdateState.failed
            return

        self._log("Git update completed successfully")

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
