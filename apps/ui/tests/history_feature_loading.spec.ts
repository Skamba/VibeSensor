import { expect, test } from "vitest";
import { createAppState } from "../src/app/ui_app_state";
import {
  createFeatureHarness,
  historyInsightsAnalyzingPayload,
  historyInsightsPayload,
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

test("history feature refreshes runs and renders an empty-state model", async () => {
  const { feature, historySummary, deleteAllRunsBtn, getLatestModel } =
    createFeatureHarness();
  mswServer.use(
    ...buildHistoryHandlers({
      list: makeHistoryListPayload({ runs: [] }),
    }),
  );

  await feature.refreshHistory();

  const model = getLatestModel();
  expect(historySummary.textContent).toBe("history.none");
  expect(deleteAllRunsBtn.disabled).toBe(true);
  expect(model?.table?.kind).toBe("empty");
  if (model?.table?.kind === "empty") {
    expect(model.table.t("history.empty.title")).toBe("history.empty.title");
  }
});

test("history feature refreshes runs and renders table state", async () => {
  const state = createAppState();
  const { feature, historySummary, deleteAllRunsBtn, getLatestModel } =
    createFeatureHarness(state);
  mswServer.use(
    ...buildHistoryHandlers({
      list: makeHistoryListPayload({
        runs: [historyListRun("run-001", { status: "analyzing" })],
      }),
    }),
  );

  await feature.refreshHistory();

  expect(state.history.runs.value).toHaveLength(1);
  expect(historySummary.textContent).toContain("history.available_count");
  expect(getLatestModel()?.table?.kind).toBe("rows");
  const row = latestRowModels({ getLatestModel })[0];
  expect(row.runId).toBe("run-001");
  expect(row.isExpanded).toBe(false);
  expect(row.summaryChips.map((chip) => chip.text)).toContain(
    "history.row_status.analyzing",
  );
  expect(row.summaryHeadline).toBe("history.row_status.analyzing");
  expect(row.carName).toBe("Track Car");
  expect(row.toggleLabel).toBe("history.open_diagnosis");
  expect(row.details).toBeNull();
  expect(deleteAllRunsBtn.disabled).toBe(false);
});

test("history feature reloads the expanded run when the language changes", async () => {
  const state = createAppState();
  state.history.runs.value = [historyListRun("run-001")];
  const { feature, getRenderCount } = createFeatureHarness(state);
  const requests: string[] = [];
  mswServer.use(
    ...buildHistoryHandlers({
      insights: (request) => {
        const url = new URL(request.url);
        const requestPath = `${url.pathname}${url.search}`;
        requests.push(requestPath);
        if (requestPath === "/api/history/run-001/insights?lang=en") {
          return historyInsightsPayload("run-001", 1);
        }
        if (requestPath === "/api/history/run-001/insights?lang=nl") {
          return historyInsightsPayload("run-001", 2);
        }
        return { detail: `Unexpected request: ${requestPath}`, status: 500 };
      },
    }),
  );

  feature.toggleRunDetails("run-001");
  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-001"]?.preview
          ?.sensor_count_used ?? null,
    )
    .toBe(1);
  await feature.onHistoryTableAction("load-insights", "run-001");
  expect(
    state.history.runDetailsById.value["run-001"]?.insights?.sensor_count_used,
  ).toBe(1);

  state.shell.lang.value = "nl";
  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-001"]?.preview
          ?.sensor_count_used ?? null,
    )
    .toBe(2);
  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-001"]?.insights
          ?.sensor_count_used ?? null,
    )
    .toBe(2);

  expect(getRenderCount()).toBeGreaterThanOrEqual(6);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=nl",
    "/api/history/run-001/insights?lang=nl",
  ]);
});

test("history feature treats analyzing insights responses as unavailable", async () => {
  const state = createAppState();
  state.history.runs.value = [historyListRun("run-001")];
  const { feature, getRenderCount } = createFeatureHarness(state);
  const requests: string[] = [];
  mswServer.use(
    ...buildHistoryHandlers({
      insights: (request) => {
        const url = new URL(request.url);
        const requestPath = `${url.pathname}${url.search}`;
        requests.push(requestPath);
        if (requestPath === "/api/history/run-001/insights?lang=en") {
          return {
            json: historyInsightsAnalyzingPayload("run-001"),
            status: 202,
          };
        }
        return { detail: `Unexpected request: ${requestPath}`, status: 500 };
      },
    }),
  );

  feature.toggleRunDetails("run-001");
  await expect
    .poll(
      () =>
        state.history.runDetailsById.value["run-001"]?.previewLoading ?? false,
    )
    .toBe(false);
  await feature.onHistoryTableAction("load-insights", "run-001");

  expect(state.history.runDetailsById.value["run-001"]?.preview).toBeNull();
  expect(state.history.runDetailsById.value["run-001"]?.previewError).toBe("");
  expect(state.history.runDetailsById.value["run-001"]?.insights).toBeNull();
  expect(state.history.runDetailsById.value["run-001"]?.insightsError).toBe("");
  expect(getRenderCount()).toBeGreaterThanOrEqual(4);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
  ]);
});
