"""Correct the times of runs recorded before the Pi clock was set.

A run started on an untrusted clock (``clock_trusted`` false) is stored with
``start_time_unverified`` and its start on the monotonic clock plus the boot
id. Once the clock is trusted, NTP-synchronised or set by a browser, runs from
the same boot get their true times (``HistoryDB.correct_unverified_run_times``).
Runs from an earlier boot keep the flag: their monotonic start means nothing now.

``correct`` runs at startup, after every browser clock report, after every
post-analysis (a run still analysing when the clock was set is corrected once
its analysis is stored) and when ``watch`` sees the clock become trusted with no
browser connected (NTP synchronised it).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from vibesensor.clock.boot import current_boot_id

if TYPE_CHECKING:
    from vibesensor.history.history_db import HistoryDB

__all__ = ["CLOCK_TRUST_POLL_S", "RunTimeCorrector"]

LOGGER = logging.getLogger(__name__)

CLOCK_TRUST_POLL_S = 30.0
"""How often ``watch`` reads the clock verdict (an ``adjtimex`` call, no I/O)."""


class RunTimeCorrector:
    """Re-date this boot's unverified runs once the wall clock is trusted."""

    __slots__ = (
        "_boot_id",
        "_clock_trusted",
        "_history_db",
        "_monotonic",
        "_now",
        "_time_zone",
    )

    def __init__(
        self,
        *,
        history_db: HistoryDB,
        clock_trusted: Callable[[], bool],
        time_zone: Callable[[], str | None],
        boot_id: Callable[[], str | None] = current_boot_id,
        now: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._history_db = history_db
        self._clock_trusted = clock_trusted
        self._time_zone = time_zone
        self._boot_id = boot_id()
        self._now = now
        self._monotonic = monotonic

    def correct(self) -> list[str]:
        """Correct what can be corrected now; return the corrected run ids."""
        if self._boot_id is None or not self._clock_trusted():
            return []
        try:
            corrected = self._history_db.correct_unverified_run_times(
                boot_id=self._boot_id,
                wall_now_s=self._now(),
                monotonic_now_s=self._monotonic(),
                time_zone=self._time_zone(),
            )
        except (sqlite3.Error, RuntimeError) as exc:
            LOGGER.warning("Could not correct the times of unverified runs: %s", exc)
            return []
        if corrected:
            LOGGER.info(
                "Corrected the start and end times of %d run(s) recorded before the "
                "clock was set: %s",
                len(corrected),
                ", ".join(corrected),
            )
        return corrected

    async def watch(self, *, poll_s: float = CLOCK_TRUST_POLL_S) -> None:
        """Correct each time the clock becomes trusted, e.g. NTP syncs with no browser open.

        The first poll counts as a change, which covers a clock trusted between
        the startup correction and this task starting.
        """
        trusted = False
        while True:
            await asyncio.sleep(poll_s)
            was_trusted, trusted = trusted, self._clock_trusted()
            if trusted and not was_trusted:
                await asyncio.to_thread(self.correct)
