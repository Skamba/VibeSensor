import { afterEach, describe, expect, test, vi } from "vitest";

import {
  browserTimeZone,
  createClockReporter,
  reportClock,
} from "../src/clock_report";
import { runsChanged } from "../src/live_store";

const NOTHING_CORRECTED = { runs_corrected: 0 };

describe("createClockReporter", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  test("reports the browser clock and zone once per (re)connect", () => {
    vi.useFakeTimers({ now: 1_700_000_000_000 });
    const report = vi.fn(() => Promise.resolve(NOTHING_CORRECTED));
    const onConnection = createClockReporter(report);

    onConnection(false);
    onConnection(true);
    onConnection(true);
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenLastCalledWith(
      1_700_000_000_000,
      browserTimeZone(),
    );

    onConnection(false);
    vi.setSystemTime(1_700_000_060_000);
    onConnection(true);
    expect(report).toHaveBeenCalledTimes(2);
    expect(report).toHaveBeenLastCalledWith(
      1_700_000_060_000,
      browserTimeZone(),
    );
  });

  test("a failed report is logged, not thrown", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const onConnection = createClockReporter(() =>
      Promise.reject(new Error("offline")),
    );

    onConnection(true);
    await vi.waitFor(() => {
      expect(warn).toHaveBeenCalledWith(
        "Browser clock report failed",
        expect.any(Error),
      );
    });
    warn.mockRestore();
  });
});

test("reportClock waits for the report and swallows its failure", async () => {
  let resolveReport: () => void = () => undefined;
  const report = vi.fn(
    () =>
      new Promise<typeof NOTHING_CORRECTED>((resolve) => {
        resolveReport = () => resolve(NOTHING_CORRECTED);
      }),
  );
  let done = false;
  const pending = reportClock(report).then(() => {
    done = true;
  });
  await Promise.resolve();
  expect(report).toHaveBeenCalledWith(expect.any(Number), browserTimeZone());
  expect(done).toBe(false);
  resolveReport();
  await pending;
  expect(done).toBe(true);

  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  await expect(
    reportClock(() => Promise.reject(new Error("offline"))),
  ).resolves.toBeUndefined();
  expect(warn).toHaveBeenCalledWith(
    "Browser clock report failed",
    expect.any(Error),
  );
  warn.mockRestore();
});

test("a report that re-dated runs reloads History", async () => {
  const before = runsChanged.peek();
  await reportClock(() => Promise.resolve(NOTHING_CORRECTED));
  expect(runsChanged.peek()).toBe(before);

  // The Pi clock was set: runs recorded on the unset clock got their true times.
  await reportClock(() => Promise.resolve({ runs_corrected: 2 }));
  expect(runsChanged.peek()).toBe(before + 1);
});

test("browserTimeZone names an IANA zone", () => {
  expect(browserTimeZone()).toMatch(/^[A-Za-z_]+(\/[A-Za-z_+\-0-9]+)*$/);
});
