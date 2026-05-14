import { expect, test } from "vitest";
import { createAppState } from "../src/app/ui_app_state";
import { jsonResponse } from "./async_test_helpers";
import {
  createFeatureHarness,
  historyInsightsWithFindingsPayload,
  historyListRun,
  installHistoryFeatureTestLifecycle,
  latestRowModels,
  mswServer,
} from "./history_feature_test_support";
import {
  buildHistoryHandlers,
  makeHistoryListPayload,
} from "./msw/handlers/history";

installHistoryFeatureTestLifecycle();

test("history feature preloads collapsed row context for completed runs", async () => {
  const state = createAppState();
  const { feature, getLatestModel } = createFeatureHarness(state);
  const requests: string[] = [];
  mswServer.use(
    ...buildHistoryHandlers({
      insights: (request) => {
        const url = new URL(request.url);
        const requestPath = `${url.pathname}${url.search}`;
        requests.push(requestPath);
        if (requestPath === "/api/history/run-001/insights?lang=en") {
          return historyInsightsWithFindingsPayload("run-001", 2);
        }
        return { detail: `Unexpected request: ${requestPath}`, status: 500 };
      },
      list: (request) => {
        const url = new URL(request.url);
        requests.push(url.pathname);
        if (url.pathname === "/api/history") {
          return { runs: [historyListRun("run-001")] };
        }
        return { detail: `Unexpected request: ${url.pathname}`, status: 500 };
      },
    }),
  );

  await feature.refreshHistory();
  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-001"]?.preview
          ?.sensor_count_used ?? null,
    )
    .toBe(2);

  const row = latestRowModels({ getLatestModel })[0];
  expect(row.summaryChips.map((chip) => chip.text)).toContain(
    "history.row_status.complete",
  );
  expect(row.summaryHeadline).toBe("Front-right wheel imbalance");
  expect(row.summaryMeta?.includes("report.confidence")).toBe(true);
  expect(requests).toEqual([
    "/api/history",
    "/api/history/run-001/insights?lang=en",
  ]);
});

test("history feature prefetches collapsed run previews in parallel batches", async () => {
  const state = createAppState();
  const { feature } = createFeatureHarness(state);
  const previewRequests: string[] = [];
  const previewResolvers = new Map<string, (response: Response) => void>();
  mswServer.use(
    ...buildHistoryHandlers({
      insights: async (request) => {
        const url = new URL(request.url);
        const requestPath = `${url.pathname}${url.search}`;
        if (
          requestPath.startsWith("/api/history/run-") &&
          requestPath.endsWith("/insights?lang=en")
        ) {
          previewRequests.push(requestPath);
          return await new Promise<Response>((resolve) => {
            previewResolvers.set(requestPath, resolve);
          });
        }
        return { detail: `Unexpected request: ${requestPath}`, status: 500 };
      },
      list: makeHistoryListPayload({
        runs: [
          historyListRun("run-001"),
          historyListRun("run-002"),
          historyListRun("run-003"),
          historyListRun("run-004"),
        ],
      }),
    }),
  );

  await feature.refreshHistory();
  await expect.poll(() => previewRequests.length).toBe(3);

  previewResolvers
    .get("/api/history/run-001/insights?lang=en")
    ?.call(
      null,
      jsonResponse(historyInsightsWithFindingsPayload("run-001", 2)),
    );
  previewResolvers
    .get("/api/history/run-002/insights?lang=en")
    ?.call(
      null,
      jsonResponse(historyInsightsWithFindingsPayload("run-002", 2)),
    );
  previewResolvers
    .get("/api/history/run-003/insights?lang=en")
    ?.call(
      null,
      jsonResponse(historyInsightsWithFindingsPayload("run-003", 2)),
    );

  await expect.poll(() => previewRequests.length).toBe(4);

  previewResolvers
    .get("/api/history/run-004/insights?lang=en")
    ?.call(
      null,
      jsonResponse(historyInsightsWithFindingsPayload("run-004", 2)),
    );

  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-004"]?.preview
          ?.sensor_count_used ?? null,
    )
    .toBe(2);

  expect(previewRequests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-002/insights?lang=en",
    "/api/history/run-003/insights?lang=en",
    "/api/history/run-004/insights?lang=en",
  ]);
});
