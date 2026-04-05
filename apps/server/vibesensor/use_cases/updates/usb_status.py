from __future__ import annotations

from pathlib import Path
from typing import Protocol

from vibesensor.use_cases.updates.models import UsbInternetStatus
from vibesensor.use_cases.updates.privilege import build_sudo_args
from vibesensor.use_cases.updates.runner import CommandRunner
from vibesensor.use_cases.updates.usb_status_evaluation import (
    candidate_diagnostic,
    select_best_candidate,
    should_attempt_activation,
    status_from_candidate,
)
from vibesensor.use_cases.updates.usb_status_inspection import (
    DEFAULT_SYS_CLASS_NET,
    UsbInternetStatusInspector,
)

_USB_ACTIVATION_WAIT_S = 15

__all__ = [
    "UsbInternetStatusReader",
    "UsbInternetStatusService",
]


class UsbInternetStatusReader(Protocol):
    async def snapshot(self, *, activate: bool = False) -> UsbInternetStatus: ...


class UsbInternetStatusService:
    """Inspect live Linux/NM state to determine whether USB internet is available."""

    __slots__ = ("_inspector", "_runner")

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        sys_class_net: Path = DEFAULT_SYS_CLASS_NET,
    ) -> None:
        command_runner = runner or CommandRunner()
        self._runner = command_runner
        self._inspector = UsbInternetStatusInspector(
            runner=command_runner,
            sys_class_net=sys_class_net,
        )

    async def _activate_interface(self, interface_name: str) -> str:
        rc, stdout, stderr = await self._runner.run(
            build_sudo_args(
                [
                    "nmcli",
                    "--wait",
                    str(_USB_ACTIVATION_WAIT_S),
                    "device",
                    "up",
                    interface_name,
                ]
            ),
            timeout=float(_USB_ACTIVATION_WAIT_S + 5),
        )
        if rc == 0:
            return ""
        return (stderr or stdout or f"exit {rc}").strip()

    async def snapshot(self, *, activate: bool = False) -> UsbInternetStatus:
        candidate_statuses = await self._inspector.collect_candidates()
        if not candidate_statuses:
            return UsbInternetStatus(
                detected=False,
                usable=False,
                diagnostic="No USB network interface is currently detected.",
            )

        best = select_best_candidate(candidate_statuses)
        if not activate or not should_attempt_activation(best):
            return status_from_candidate(best)

        activation_error = await self._activate_interface(best.interface_name)
        candidate_statuses = await self._inspector.collect_candidates()
        if not candidate_statuses:
            diagnostic = "USB network interface disappeared while attempting activation."
            if activation_error:
                diagnostic = f"{diagnostic} Auto-activation failed ({activation_error})."
            return UsbInternetStatus(detected=False, usable=False, diagnostic=diagnostic)

        best = select_best_candidate(candidate_statuses)
        if activation_error and not best.usable:
            return status_from_candidate(
                best,
                diagnostic=(
                    f"{candidate_diagnostic(best)} Auto-activation failed ({activation_error})."
                ),
            )
        return status_from_candidate(best)
