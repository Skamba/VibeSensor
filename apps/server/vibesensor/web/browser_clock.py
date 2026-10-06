"""Browser clock report: steps an unsynchronised Pi clock and stores the user's time zone."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.web.models.settings import BrowserClockRequest, BrowserClockResponse

if TYPE_CHECKING:
    from vibesensor.clock.browser_clock import BrowserClockCorrector
    from vibesensor.settings.ui_preferences import UiPreferencesService

LOGGER = logging.getLogger(__name__)


def create_browser_clock_routes(
    clock: BrowserClockCorrector,
    ui_preferences: UiPreferencesService,
) -> APIRouter:
    """Create the route the UI calls on every (re)connect."""

    router = APIRouter(tags=["system"])

    @router.post("/api/system/browser-clock", response_model=BrowserClockResponse)
    async def report_browser_clock(req: BrowserClockRequest) -> BrowserClockResponse:
        """Store the browser's time zone, then step an unsynchronised system clock to its clock.

        The zone goes first: the report re-dates runs recorded on the unset
        clock, and their local times use the stored zone.
        """

        if req.time_zone is not None:
            try:
                await asyncio.to_thread(ui_preferences.set_time_zone, req.time_zone)
            except ValueError:
                # A zone this Pi's tzdata lacks; keep the clock result, keep the old zone.
                LOGGER.info("Ignoring unknown browser time zone %r", req.time_zone)
        result = await asyncio.to_thread(clock.report, req.epoch_ms)
        return BrowserClockResponse(
            action=result.action.value,
            offset_s=result.offset_s,
            time_zone=ui_preferences.time_zone,
            runs_corrected=result.runs_corrected,
        )

    return router
