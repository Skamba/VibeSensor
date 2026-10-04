import { reportBrowserClock } from "./api/settings";
import { uiLogger } from "./ui_logger";

/** The browser's IANA time zone, or null when the runtime does not expose one. */
export function browserTimeZone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

/**
 * Returns a callback fed with the live-connection state. On every
 * (re)connect it reports the browser clock and time zone: the Pi has no RTC,
 * so the server steps its clock when it is unsynchronised, and reports show
 * run times in the user's zone instead of the image default.
 */
export function createClockReporter(
  report: (
    epochMs: number,
    timeZone: string | null,
  ) => Promise<unknown> = reportBrowserClock,
): (connected: boolean) => void {
  let wasConnected = false;
  return (connected) => {
    if (connected && !wasConnected) {
      report(Date.now(), browserTimeZone()).catch((error: unknown) => {
        uiLogger.warn("Browser clock report failed", error);
      });
    }
    wasConnected = connected;
  };
}
