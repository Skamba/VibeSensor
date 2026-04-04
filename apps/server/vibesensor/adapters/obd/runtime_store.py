"""Shared runtime store for focused Bluetooth OBD services."""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import RLock

from vibesensor.adapters.obd.polling import ObdPollingCadence
from vibesensor.adapters.obd.runtime_policy import ObdRuntimePolicy
from vibesensor.adapters.obd.runtime_state import ObdRuntimeState

__all__ = ["MonotonicFn", "ObdRuntimeStore"]

MonotonicFn = Callable[[], float]


class ObdRuntimeStore:
    """Own the shared lock, policy, polling cadence, and observed runtime state."""

    __slots__ = ("_lock", "monotonic", "polling", "policy", "state")

    def __init__(
        self,
        *,
        monotonic: MonotonicFn = time.monotonic,
        poll_interval_s: float,
        initial_reconnect_delay_s: float,
        engine_rpm_stale_timeout_s: float,
    ) -> None:
        self._lock = RLock()
        self.monotonic = monotonic
        self.polling = ObdPollingCadence(max_interval_s=poll_interval_s)
        self.policy = ObdRuntimePolicy(monotonic=monotonic)
        self.state = ObdRuntimeState(
            initial_reconnect_delay_s=initial_reconnect_delay_s,
            engine_rpm_stale_timeout_s=engine_rpm_stale_timeout_s,
        )
