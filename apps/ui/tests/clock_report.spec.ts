import { afterEach, describe, expect, test, vi } from "vitest";

import { browserTimeZone, createClockReporter } from "../src/clock_report";

describe("createClockReporter", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  test("reports the browser clock and zone once per (re)connect", () => {
    vi.useFakeTimers({ now: 1_700_000_000_000 });
    const report = vi.fn(() => Promise.resolve());
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

test("browserTimeZone names an IANA zone", () => {
  expect(browserTimeZone()).toMatch(/^[A-Za-z_]+(\/[A-Za-z_+\-0-9]+)*$/);
});
