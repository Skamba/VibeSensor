import { expect, test } from "@playwright/test";

import { addSettingsCar } from "../src/api/settings";
import { getHistoryInsights } from "../src/api/history";
import { getLoggingStatus } from "../src/api/logging";
import type {
  CarUpsertRequest,
  CarsPayload,
  HistoryInsightsAnalyzingPayload,
  LoggingStatusPayload,
} from "../src/api/types";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";

test.describe("API adapter clone usage", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("returns logging status without structuredClone", async () => {
    const originalFetch = globalThis.fetch;
    const originalStructuredClone = globalThis.structuredClone;
    const payload: LoggingStatusPayload = {
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: null,
    };
    let structuredCloneCalls = 0;

    globalThis.structuredClone = ((value: unknown) => {
      structuredCloneCalls += 1;
      return originalStructuredClone(value);
    }) as typeof structuredClone;
    globalThis.fetch = (async () => jsonResponse(payload)) as typeof fetch;

    try {
      await expect(getLoggingStatus()).resolves.toEqual(payload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.structuredClone = originalStructuredClone;
    }
  });

  test("serializes car payloads without structuredClone", async () => {
    const originalFetch = globalThis.fetch;
    const originalStructuredClone = globalThis.structuredClone;
    const requestPayload: CarUpsertRequest = {
      name: "Project Car",
      type: "Sedan",
      variant: "Prototype",
      aspects: {
        tire_width_mm: 225,
        current_gear_ratio: 0.82,
      },
    };
    const responsePayload: CarsPayload = {
      active_car_id: null,
      cars: [],
    };
    let structuredCloneCalls = 0;
    let requestBody = "";

    globalThis.structuredClone = ((value: unknown) => {
      structuredCloneCalls += 1;
      return originalStructuredClone(value);
    }) as typeof structuredClone;
    globalThis.fetch = (async (_input: string | URL | RequestInfo, init?: RequestInit) => {
      requestBody = String(init?.body ?? "");
      return jsonResponse(responsePayload);
    }) as typeof fetch;

    try {
      await expect(addSettingsCar(requestPayload)).resolves.toEqual(responsePayload);
      expect(JSON.parse(requestBody)).toEqual(requestPayload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.structuredClone = originalStructuredClone;
    }
  });

  test("returns history insights bodies without structuredClone", async () => {
    const originalFetch = globalThis.fetch;
    const originalStructuredClone = globalThis.structuredClone;
    const payload: HistoryInsightsAnalyzingPayload = {
      status: "analyzing",
      run_id: "run-001",
    };
    let structuredCloneCalls = 0;

    globalThis.structuredClone = ((value: unknown) => {
      structuredCloneCalls += 1;
      return originalStructuredClone(value);
    }) as typeof structuredClone;
    globalThis.fetch = (async () => jsonResponse(payload, { status: 202 })) as typeof fetch;

    try {
      await expect(getHistoryInsights("run-001", "en")).resolves.toEqual(payload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.fetch = originalFetch;
      globalThis.structuredClone = originalStructuredClone;
    }
  });
});
