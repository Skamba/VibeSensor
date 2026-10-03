import { beforeEach, describe, expect, test } from "vitest";
import { addSettingsCar } from "../src/api/settings";
import { getHistoryInsights } from "../src/api/history";
import { getLoggingStatus } from "../src/api/logging";
import type {
  CarsPayload,
  CarUpsertRequest,
  HistoryInsightsAnalyzingPayload,
  LoggingStatusPayload,
} from "../src/api/types";
import { installWindowGlobal } from "./async_test_helpers";
import { json, route, stubFetch } from "./fetch_stub";

const server = stubFetch();

describe("API adapter clone usage", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("returns logging status without structuredClone", async () => {
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
    server.use(route("GET /api/recording/status", () => json(payload)));

    try {
      await expect(getLoggingStatus()).resolves.toEqual(payload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.structuredClone = originalStructuredClone;
    }
  });

  test("serializes car payloads without structuredClone", async () => {
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
    const responsePayload: CarsPayload = { active_car_id: null, cars: [] };
    let structuredCloneCalls = 0;
    let requestBody = "";

    globalThis.structuredClone = ((value: unknown) => {
      structuredCloneCalls += 1;
      return originalStructuredClone(value);
    }) as typeof structuredClone;
    server.use(
      route("POST /api/settings/cars", async (request) => {
        requestBody = await request.text();
        return json(responsePayload);
      }),
    );

    try {
      await expect(addSettingsCar(requestPayload)).resolves.toEqual(
        responsePayload,
      );
      expect(JSON.parse(requestBody)).toEqual(requestPayload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.structuredClone = originalStructuredClone;
    }
  });

  test("returns history insights bodies without structuredClone", async () => {
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
    server.use(
      route("GET /api/history/run-001/insights", () =>
        json(payload, { status: 202 }),
      ),
    );

    try {
      await expect(getHistoryInsights("run-001", "en")).resolves.toEqual(
        payload,
      );
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.structuredClone = originalStructuredClone;
    }
  });
});
