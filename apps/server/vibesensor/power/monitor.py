"""Watch the Pi's supply voltage and SoC temperature.

A Pi 3 A+ on a car USB port can brown out, and a closed car in the sun can
heat it until the firmware slows the CPU. Either can thin out or spoil a
recording, and the system journal is gone after the next power cut unless it
is persistent (``systemd/vibesensor-journald.conf``). :class:`PowerMonitor`
reads two sysfs files once a second, without a subprocess:

- ``in0_lcrit_alarm`` of the ``rpi_volt`` hwmon device: 1 when the firmware saw
  the supply below about 4.63 V. The kernel driver asks the firmware every 2 s
  and clears the firmware's sticky bit each time, so a short dip holds the
  alarm for one 2 s window; polling once a second sees every window.
  ``vcgencmd get_throttled`` reads the same bits, but needs a subprocess, and
  that driver clears its "has occurred" bits.
- ``thermal_zone0/temp``: the SoC temperature in millidegrees Celsius.

On a Pi 3 A+ the firmware lowers the CPU clock from 1.4 to 1.2 GHz at 60 °C
(its soft limit, ``warm`` here) and throttles harder from 80 °C (``hot``). A
state is left only 3 °C below its threshold, so a reading that hovers at a
threshold logs once.

Every transition goes to the app log, which lives in the data directory and
outlives a power cut. What this boot has seen is kept in ``power_state.json``
next to the history DB, so a server restart (an update) does not forget it. A
run stores the issues seen while it recorded (:meth:`PowerMonitor.issues_since`)
and its report and History entry say that the results may be affected.

Off a Pi the files are missing: the voltage reads ``None`` and, without a
thermal zone, the temperature ``unknown``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, Literal, TypedDict

import anyio

from vibesensor.clock.boot import current_boot_id
from vibesensor.common.structured_logging import log_extra

__all__ = [
    "POWER_ISSUES",
    "PowerIssue",
    "PowerMonitor",
    "PowerSnapshot",
    "TemperatureState",
    "find_undervoltage_alarm",
    "temperature_state",
]

LOGGER = logging.getLogger(__name__)

TemperatureState = Literal["unknown", "normal", "warm", "hot"]
PowerIssue = Literal["undervoltage", "overheated"]
POWER_ISSUES: Final[tuple[PowerIssue, ...]] = ("undervoltage", "overheated")

POLL_INTERVAL_S: Final = 1.0
WARM_C: Final = 60.0
"""The Pi 3 A+/3 B+ firmware soft limit: the CPU clock drops to 1.2 GHz."""
HOT_C: Final = 80.0
"""The firmware throttles the CPU further from here."""
HYSTERESIS_C: Final = 3.0

HWMON_DIR: Final = Path("/sys/class/hwmon")
THERMAL_PATH: Final = Path("/sys/class/thermal/thermal_zone0/temp")

_RANK: Final[dict[TemperatureState, int]] = {"unknown": 0, "normal": 1, "warm": 2, "hot": 3}
_TEMPERATURE_MEANING: Final[dict[TemperatureState, str]] = {
    "normal": "back below the 60 °C soft limit",
    "warm": "at the 60 °C soft limit; the firmware lowers the CPU clock",
    "hot": "above 80 °C; the firmware throttles the CPU",
}


class PowerSnapshot(TypedDict):
    undervoltage_now: bool | None
    """``None`` when there is no ``rpi_volt`` sensor (not a Pi)."""
    undervoltage_seen: bool
    """Since boot."""
    temperature_c: float | None
    temperature_state: TemperatureState
    hottest_state_seen: TemperatureState
    """Since boot."""


def find_undervoltage_alarm(hwmon_dir: Path = HWMON_DIR) -> Path | None:
    """The ``rpi_volt`` undervoltage alarm file, or ``None`` off a Pi."""
    for device in sorted(hwmon_dir.glob("hwmon*")):
        try:
            name = (device / "name").read_text(encoding="ascii").strip()
        except OSError:
            continue
        alarm = device / "in0_lcrit_alarm"
        if name == "rpi_volt" and alarm.is_file():
            return alarm
    return None


def temperature_state(temperature_c: float, previous: TemperatureState) -> TemperatureState:
    """The state for *temperature_c*; *previous* is left only past the hysteresis."""
    if temperature_c >= HOT_C:
        state: TemperatureState = "hot"
    elif temperature_c >= WARM_C:
        state = "warm"
    else:
        state = "normal"
    if _RANK[state] >= _RANK[previous]:
        return state
    if previous == "hot" and temperature_c > HOT_C - HYSTERESIS_C:
        return "hot"
    if previous in ("hot", "warm") and temperature_c > WARM_C - HYSTERESIS_C:
        return "warm"
    return state


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


class PowerMonitor:
    """Poll the supply-voltage alarm and the SoC temperature; see the module docstring."""

    __slots__ = (
        "_alarm_path",
        "_boot_id",
        "_hottest_seen",
        "_last_seen",
        "_monotonic",
        "_state_path",
        "_temperature_c",
        "_temperature_state",
        "_thermal_path",
        "_undervoltage_now",
        "_undervoltage_seen",
        "_undervoltage_since",
    )

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        hwmon_dir: Path = HWMON_DIR,
        thermal_path: Path = THERMAL_PATH,
        monotonic: Callable[[], float] = time.monotonic,
        boot_id: Callable[[], str | None] = current_boot_id,
    ) -> None:
        self._alarm_path = find_undervoltage_alarm(hwmon_dir)
        self._thermal_path = thermal_path
        self._monotonic = monotonic
        self._undervoltage_now: bool | None = None
        self._undervoltage_since = 0.0
        self._undervoltage_seen = False
        self._temperature_c: float | None = None
        self._temperature_state: TemperatureState = "unknown"
        self._hottest_seen: TemperatureState = "unknown"
        # Monotonic time of the last poll that saw each issue.
        self._last_seen: dict[PowerIssue, float] = {}
        current_boot = boot_id()
        self._boot_id = current_boot
        # No boot id (non-Linux) means no way to tell a restart from a reboot.
        self._state_path = state_path if current_boot is not None else None
        self._load_state()

    async def run(self) -> None:
        """Poll forever; the reads are a few microseconds of sysfs, so no thread."""
        while True:
            self.poll()
            await anyio.sleep(POLL_INTERVAL_S)

    def poll(self) -> None:
        """Read both sensors once, log transitions, and save what this boot has seen."""
        now = self._monotonic()
        seen_before = (self._undervoltage_seen, self._hottest_seen)
        self._poll_voltage(now)
        self._poll_temperature(now)
        if (self._undervoltage_seen, self._hottest_seen) != seen_before:
            self._save_state()

    def snapshot(self) -> PowerSnapshot:
        return {
            "undervoltage_now": self._undervoltage_now,
            "undervoltage_seen": self._undervoltage_seen,
            "temperature_c": (
                None if self._temperature_c is None else round(self._temperature_c, 1)
            ),
            "temperature_state": self._temperature_state,
            "hottest_state_seen": self._hottest_seen,
        }

    def issues_since(self, start_mono_s: float) -> tuple[PowerIssue, ...]:
        """The issues a poll saw at or after *start_mono_s* (``time.monotonic`` seconds)."""
        return tuple(
            issue for issue in POWER_ISSUES if self._last_seen.get(issue, -math.inf) >= start_mono_s
        )

    def _poll_voltage(self, now: float) -> None:
        if self._alarm_path is None:
            return
        alarm = _read_int(self._alarm_path)
        if alarm is None:
            return
        low = alarm != 0
        if low:
            self._last_seen["undervoltage"] = now
            self._undervoltage_seen = True
            if not self._undervoltage_now:
                self._undervoltage_since = now
                LOGGER.warning(
                    "Undervoltage: the Pi's supply dropped below 4.63 V and the firmware "
                    "slows the CPU; use a stronger USB port or a 5 V 2.5 A supply",
                    extra=log_extra(event="power_undervoltage"),
                )
        elif self._undervoltage_now:
            lasted_s = now - self._undervoltage_since
            LOGGER.info(
                "Supply voltage back to normal after %.0f s of undervoltage",
                lasted_s,
                extra=log_extra(event="power_undervoltage_cleared", duration_s=round(lasted_s, 1)),
            )
        self._undervoltage_now = low

    def _poll_temperature(self, now: float) -> None:
        millidegrees = _read_int(self._thermal_path)
        if millidegrees is None:
            return
        temperature_c = millidegrees / 1000.0
        previous = self._temperature_state
        state = temperature_state(temperature_c, previous)
        self._temperature_c = temperature_c
        self._temperature_state = state
        if state == "hot":
            self._last_seen["overheated"] = now
        if _RANK[state] > _RANK[self._hottest_seen]:
            self._hottest_seen = state
        if state == previous or (previous == "unknown" and state == "normal"):
            return
        log = LOGGER.warning if _RANK[state] > _RANK[previous] else LOGGER.info
        log(
            "SoC temperature %.1f °C: %s",
            temperature_c,
            _TEMPERATURE_MEANING[state],
            extra=log_extra(
                event="power_temperature",
                temperature_state=state,
                temperature_c=round(temperature_c, 1),
            ),
        )

    def _load_state(self) -> None:
        if self._state_path is None:
            return
        try:
            state = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            LOGGER.warning("Ignoring unreadable power state %s: %s", self._state_path, exc)
            return
        if not isinstance(state, dict) or state.get("boot_id") != self._boot_id:
            return
        self._undervoltage_seen = state.get("undervoltage_seen") is True
        hottest = state.get("hottest_state_seen")
        if isinstance(hottest, str) and hottest in _RANK:
            self._hottest_seen = hottest

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        state = {
            "boot_id": self._boot_id,
            "undervoltage_seen": self._undervoltage_seen,
            "hottest_state_seen": self._hottest_seen,
        }
        tmp_path = self._state_path.with_name(f".{self._state_path.name}.tmp")
        try:
            tmp_path.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp_path, self._state_path)
        except OSError as exc:
            LOGGER.warning("Could not save power state to %s: %s", self._state_path, exc)
