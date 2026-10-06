import { reportBrowserClock } from "./api/settings";
import type { BrowserClockPayload } from "./api/types";
import { runsChanged } from "./live_store";
import { uiLogger } from "./ui_logger";

/** The browser's IANA time zone, or null when the runtime does not expose one. */
export function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

type ClockReport = (
  epochMs: number,
  timeZone: string | null,
) => Promise<Pick<BrowserClockPayload, "runs_corrected">>;

/**
 * Reports the browser clock and time zone now. The Pi has no RTC, so the
 * server steps its clock when it is unsynchronised, and reports show run
 * times in the user's zone instead of the image default. When the report
 * re-dated runs recorded on the unset clock, History reloads. A failed report
 * is logged, never thrown.
 */
export async function reportClock(
  report: ClockReport = reportBrowserClock,
): Promise<void> {
  try {
    const result = await report(Date.now(), browserTimeZone());
    if (result.runs_corrected > 0) {
      runsChanged.value += 1;
    }
  } catch (error: unknown) {
    uiLogger.warn("Browser clock report failed", error);
  }
}

/** Returns a callback fed with the live-connection state; reports the clock on every (re)connect. */
export function createClockReporter(
  report: ClockReport = reportBrowserClock,
): (connected: boolean) => void {
  let wasConnected = false;
  return (connected) => {
    if (connected && !wasConnected) {
      void reportClock(report);
    }
    wasConnected = connected;
  };
}
