import { expect, test } from "@playwright/test";

import { addSettingsCar } from "../src/api/settings";
import { getHistoryInsights } from "../src/api/history";
import { getLoggingStatus } from "../src/api/logging";
import type {
  CarUpsertRequest,
  HistoryInsightsAnalyzingPayload,
  LoggingStatusPayload,
} from "../src/api/types";
import { installWindowGlobal } from "./async_test_helpers";
import { HttpResponse, http, uiTestUrl } from "./msw/http";
import { buildCarsHandlers, makeCarsPayload } from "./msw/handlers/settings";
import { createUiMswTestServer } from "./msw/node";

const mswServer = createUiMswTestServer(test);

test.describe("API adapter clone usage", () => {
  test.beforeEach(() => {
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
    mswServer.use(http.get(uiTestUrl("/api/recording/status"), () => HttpResponse.json(payload)));

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
    const responsePayload = makeCarsPayload({ active_car_id: null, cars: [] });
    let structuredCloneCalls = 0;
    let requestBody = "";

    globalThis.structuredClone = ((value: unknown) => {
      structuredCloneCalls += 1;
      return originalStructuredClone(value);
    }) as typeof structuredClone;
    mswServer.use(
      ...buildCarsHandlers({
        create: async (request) => {
          requestBody = await request.text();
          return responsePayload;
        },
      }),
    );

    try {
      await expect(addSettingsCar(requestPayload)).resolves.toEqual(responsePayload);
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
    mswServer.use(
      http.get(uiTestUrl("/api/history/run-001/insights"), () =>
        HttpResponse.json(payload, { status: 202 }),
      ),
    );

    try {
      await expect(getHistoryInsights("run-001", "en")).resolves.toEqual(payload);
      expect(structuredCloneCalls).toBe(0);
    } finally {
      globalThis.structuredClone = originalStructuredClone;
    }
  });
});
