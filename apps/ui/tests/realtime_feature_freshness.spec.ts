import { expect, test } from "@playwright/test";

import {
  classifyDataFreshness,
  deriveDataFreshnessThresholds,
} from "../src/app/features/data_freshness";

function makeClient(overrides: Partial<{ sample_rate_hz: number; frame_samples: number }> = {}) {
  return {
    sample_rate_hz: 800,
    frame_samples: 200,
    ...overrides,
  };
}

test.describe("realtime freshness thresholds", () => {
  test("falls back to legacy thresholds when cadence metadata is missing", () => {
    expect(deriveDataFreshnessThresholds([makeClient({ frame_samples: 0 })])).toEqual({
      freshMs: 250,
      delayedMs: 1000,
    });
  });

  test("treats a healthy 400 Hz / 200-sample sensor as fresh across one frame cadence", () => {
    const clients = [makeClient({ sample_rate_hz: 400, frame_samples: 200 })];

    expect(deriveDataFreshnessThresholds(clients)).toEqual({
      freshMs: 625,
      delayedMs: 1250,
    });
    expect(classifyDataFreshness(503, clients)).toBe("fresh");
    expect(classifyDataFreshness(900, clients)).toBe("delayed");
    expect(classifyDataFreshness(1300, clients)).toBe("stale");
  });
});
