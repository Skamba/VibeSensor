import { afterEach, beforeEach, expect, test } from "vitest";
import { createHistoryFeature } from "../src/app/features/history_feature";
import { createAppState, type RunDetail } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "../src/app/views/history_table_view";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";
import {
  buildHistoryHandlers,
  makeDeleteHistoryRunPayload,
  makeHistoryListPayload,
} from "./msw/handlers/history";
import { createUiMswTestServer } from "./msw/node";
import { createTestQueryClient } from "./query_client_test_support";

const mswServer = createUiMswTestServer();
const activeHarnessCleanups: Array<() => Promise<void>> = [];

type ButtonStub = HTMLButtonElement & {
  disabled: boolean;
};

type TextStub = {
  textContent: string;
};

function createButton(): ButtonStub {
  return {
    disabled: false,
    addEventListener() {
      /* no-op */
    },
  } as unknown as ButtonStub;
}

function createTextElement(): TextStub {
  return { textContent: "" };
}

function createHistoryElements(): {
  panel: HistoryPanelView;
  historySummary: TextStub;
  deleteAllRunsBtn: ButtonStub;
  getLatestHandlers(): HistoryPanelActionHandlers | null;
  getLatestModel(): HistoryPanelRenderModel | null;
  getRenderCount(): number;
} {
  const historySummary = createTextElement();
  const deleteAllRunsBtn = createButton();
  let latestModel: HistoryPanelRenderModel | null = null;
  let latestHandlers: HistoryPanelActionHandlers | null = null;
  let renderCount = 0;
  const panel: HistoryPanelView = {
    actions: signal(null),
    model: signal(null),
  };
  effect(() => {
    latestHandlers = panel.actions.value;
  });
  effect(() => {
    const model = panel.model.value;
    if (model === null) {
      return;
    }
    const nextModel = model.value;
    renderCount += 1;
    latestModel = nextModel;
    historySummary.textContent = nextModel.historySummaryText;
    deleteAllRunsBtn.disabled = nextModel.deleteAllRunsDisabled;
  });
  return {
    panel,
    historySummary,
    deleteAllRunsBtn,
    getLatestHandlers() {
      return latestHandlers;
    },
    getLatestModel() {
      return latestModel;
    },
    getRenderCount() {
      return renderCount;
    },
  };
}

function historyInsightsPayload(runId: string, sensorCountUsed: number) {
  return {
    run_id: runId,
    status: "complete" as const,
    start_time_utc: "2026-01-01T00:00:00Z",
    duration_s: 12.3,
    sensor_count_used: sensorCountUsed,
    findings: [],
    warnings: [],
    sensor_intensity_by_location: [],
  };
}

function historyInsightsWithFindingsPayload(runId: string, sensorCountUsed: number) {
  return {
    ...historyInsightsPayload(runId, sensorCountUsed),
    most_likely_origin: {
      suspected_source: "Front-right wheel imbalance",
      location: "Front-right wheel",
      speed_band: "60-90 km/h",
      explanation: "Order content and spatial dominance agree on the front-right wheel.",
    },
    findings: [
      {
        finding_id: "finding-1",
        amplitude_metric: "db",
        confidence: 0.92,
        confidence_pct: "92%",
        confidence_tone: "success",
        evidence_summary: "Consistent wheel-order energy remains strongest at the front-right wheel.",
        frequency_hz_or_order: "1x wheel",
        strongest_location: "Front-right wheel",
        strongest_speed_band: "60-90 km/h",
        suspected_source: "Front-right wheel imbalance",
      },
      {
        finding_id: "finding-2",
        amplitude_metric: "db",
        confidence: 0.67,
        confidence_pct: "67%",
        confidence_tone: "warn",
        evidence_summary: "Secondary driveline energy appears at the tunnel but is weaker than the wheel finding.",
        frequency_hz_or_order: "1x driveshaft",
        strongest_location: "Driveshaft tunnel",
        strongest_speed_band: "70-90 km/h",
        suspected_source: "Secondary driveline contribution",
      },
    ],
    sensor_intensity_by_location: [
      {
        location: "Front Right Wheel",
        p50_intensity_db: 18,
        p95_intensity_db: 32,
        max_intensity_db: 40,
        dropped_frames_delta: 0,
        queue_overflow_drops_delta: 0,
        sample_count: 20,
      },
    ],
  };
}

function historyInsightsAnalyzingPayload(runId: string) {
  return {
    run_id: runId,
    status: "analyzing" as const,
  };
}

function historyListRun(
  runId: string,
  overrides: Partial<{
    car_name: string;
    error_message: string | null;
    sample_count: number;
    start_time_utc: string;
    status: "complete" | "analyzing" | "error";
  }> = {},
) {
  return {
    run_id: runId,
    status: overrides.status ?? "complete",
    start_time_utc: overrides.start_time_utc ?? "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    sample_count: overrides.sample_count ?? 42,
    car_name: overrides.car_name ?? "Track Car",
    error_message: overrides.error_message ?? null,
  };
}

function testTranslation(key: string, vars?: Record<string, unknown>): string {
  return vars ? `${key}:${JSON.stringify(vars)}` : key;
}

function ensureRunDetail(state: ReturnType<typeof createAppState>, runId: string): RunDetail {
  if (!state.history.runDetailsById.value[runId]) {
    state.history.runDetailsById.value = {
      ...state.history.runDetailsById.value,
      [runId]: {
        preview: null,
        previewLoading: false,
        previewError: "",
        insights: null,
        insightsLoading: false,
        insightsError: "",
        pdfLoading: false,
        pdfError: "",
      },
    };
  }
  return state.history.runDetailsById.value[runId];
}

function latestRowModels(panel: { getLatestModel(): HistoryPanelRenderModel | null }) {
  const model = panel.getLatestModel();
  expect(model?.table?.kind).toBe("rows");
  if (!model?.table || model.table.kind !== "rows") {
    throw new Error("Expected rendered history rows");
  }
  return model.table.rows;
}

function createFeatureHarness(
  state = createAppState(),
  overrides: {
    panel?: HistoryPanelView;
    showError?: (message: string) => void;
    requestConfirmation?: (message: string) => Promise<boolean>;
    activatePrimaryView?: (viewId: string) => void;
  } = {},
) {
  const panelElements = createHistoryElements();
  const errors: string[] = [];
  const primaryViewActivations: string[] = [];
  const queryClient = createTestQueryClient();
  const feature = createHistoryFeature({
    panel: overrides.panel ?? panelElements.panel,
    navigation: {
      activatePrimaryView(viewId: string) {
        if (overrides.activatePrimaryView) {
          overrides.activatePrimaryView(viewId);
          return;
        }
        primaryViewActivations.push(viewId);
      },
    },
    history: state.history,
    queryClient,
    shell: state.shell,
    services: {
      t: testTranslation,
      requestConfirmation:
        overrides.requestConfirmation ?? (async () => true),
      showError: overrides.showError ?? ((message) => {
        errors.push(message);
      }),
    },
    formatting: {
      fmt: (value, digits = 0) => Number(value).toFixed(digits),
      fmtTs: (iso) => iso,
      formatInt: (value) => String(value),
    },
  });
  activeHarnessCleanups.push(async () => {
    feature.dispose();
    await queryClient.cancelQueries();
    queryClient.clear();
  });
  return {
    feature,
    state,
    errors,
    primaryViewActivations,
    ...panelElements,
  };
}

beforeEach(() => {
  installWindowGlobal();
});

afterEach(async () => {
  while (activeHarnessCleanups.length > 0) {
    await activeHarnessCleanups.pop()?.();
  }
});

test("history feature skips deletion when confirmation is declined", async () => {
  const state = createAppState();
  state.history.runs.value = [historyListRun("run-42")];
  const confirmationMessages: string[] = [];
  const { feature } = createFeatureHarness(state, {
    requestConfirmation: async (message) => {
      confirmationMessages.push(message);
      return false;
    },
  });

  await feature.onHistoryTableAction("delete-run", "run-42");

  expect(confirmationMessages).toEqual([
    'history.delete_confirm:{"name":"run-42"}',
  ]);
  expect(state.history.runs.value.map((run) => run.run_id)).toEqual(["run-42"]);
});

test("history feature refreshes runs and renders an empty-state model when no runs exist", async () => {
  const { feature, historySummary, deleteAllRunsBtn, getLatestModel } = createFeatureHarness();
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

test("history feature refreshes runs and renders table state through one owner", async () => {
  const state = createAppState();
  const { feature, historySummary, deleteAllRunsBtn, getLatestModel } = createFeatureHarness(state);
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
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.analyzing");
  expect(row.summaryHeadline).toBe("history.row_status.analyzing");
  expect(row.carName).toBe("Track Car");
  expect(row.carLabel).toBe("history.car_label");
  expect(row.toggleLabel).toBe("history.open_diagnosis");
  expect(row.details).toBeNull();
  expect(deleteAllRunsBtn.disabled).toBe(false);
});

test("history feature routes the open-live table action to dashboard navigation", () => {
  const { feature, getLatestHandlers, primaryViewActivations } = createFeatureHarness();
  feature.bindHandlers();

  getLatestHandlers()?.onTableInteraction({ type: "open-live" });

  expect(primaryViewActivations).toEqual(["dashboardView"]);
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
  await expect.poll(() => state.history.runDetailsById.value["run-001"]?.preview?.sensor_count_used ?? null).toBe(1);
  await feature.onHistoryTableAction("load-insights", "run-001");
  expect(state.history.runDetailsById.value["run-001"]?.insights?.sensor_count_used).toBe(1);

  state.shell.lang.value = "nl";
  await expect.poll(() => state.history.runDetailsById.value["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);
  await expect.poll(() => state.history.runDetailsById.value["run-001"]?.insights?.sensor_count_used ?? null).toBe(2);

  expect(getRenderCount()).toBeGreaterThanOrEqual(6);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=nl",
    "/api/history/run-001/insights?lang=nl",
  ]);
});

test("history feature treats analyzing insights responses as not-yet-available", async () => {
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
  await expect.poll(() => state.history.runDetailsById.value["run-001"]?.previewLoading ?? false).toBe(false);
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

test("history feature rendering promotes loaded findings ahead of supporting statistics", () => {
  const state = createAppState();
  state.history.runs.value = [historyListRun("run-001")];
  state.history.expandedRunId.value = "run-001";
  state.history.runDetailsById.value = {
    ...state.history.runDetailsById.value,
    "run-001": {
      preview: historyInsightsWithFindingsPayload("run-001", 2) as RunDetail["preview"],
      previewLoading: false,
      previewError: "",
    insights: historyInsightsWithFindingsPayload("run-001", 2) as RunDetail["insights"],
    insightsLoading: false,
    insightsError: "",
    pdfLoading: false,
      pdfError: "",
    },
  };
  const { getLatestModel } = createFeatureHarness(state);

  const row = latestRowModels({ getLatestModel })[0];
  expect(row.details?.titleEyebrow).toBe("history.details_title");
  expect(row.details?.insights.primary?.eyebrow).toBe("history.primary_diagnosis");
  expect(row.details?.heatmap.zones.find((zone) => zone.key === "front-right wheel")?.valueLabel)
    .toBe("32.0 dB");
  expect(row.details?.insights.primary?.headline).toBe("Front-right wheel imbalance");
  expect(row.details?.insights.primary?.chips.map((chip) => chip.label)).toContain("history.findings_signature");
  expect(row.details?.insights.secondaryTitle).toBe("history.secondary_candidates_title");
  expect(row.details?.insights.stateMessage).toBeNull();
  expect(row.details?.insights.visibleSecondary.map((finding) => finding.source))
    .toContain("Secondary driveline contribution");
  expect(row.details?.insights.emptyMessage).toBeNull();
  expect(row.details?.insights.primary?.nextStepLabel).toBe("history.findings_next_step_label");
  expect(row.details?.footerEyebrow).toBe("history.run_actions_title");
});

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
  await expect.poll(() => state.history.runDetailsById.value["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);

  const row = latestRowModels({ getLatestModel })[0];
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.complete");
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
        if (requestPath.startsWith("/api/history/run-") && requestPath.endsWith("/insights?lang=en")) {
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

  previewResolvers.get("/api/history/run-001/insights?lang=en")
    ?.call(null, jsonResponse(historyInsightsWithFindingsPayload("run-001", 2)));
  previewResolvers.get("/api/history/run-002/insights?lang=en")
    ?.call(null, jsonResponse(historyInsightsWithFindingsPayload("run-002", 2)));
  previewResolvers.get("/api/history/run-003/insights?lang=en")
    ?.call(null, jsonResponse(historyInsightsWithFindingsPayload("run-003", 2)));

  await expect.poll(() => previewRequests.length).toBe(4);

  previewResolvers.get("/api/history/run-004/insights?lang=en")
    ?.call(null, jsonResponse(historyInsightsWithFindingsPayload("run-004", 2)));

  await expect.poll(() => state.history.runDetailsById.value["run-004"]?.preview?.sensor_count_used ?? null)
    .toBe(2);

  expect(previewRequests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-002/insights?lang=en",
    "/api/history/run-003/insights?lang=en",
    "/api/history/run-004/insights?lang=en",
  ]);
});


test("history feature reports partial delete failures without splitting render ownership", async () => {
  const state = createAppState();
  state.history.runs.value = [
    historyListRun("run-001"),
    historyListRun("run-002"),
  ];
  state.history.expandedRunId.value = "run-001";
  ensureRunDetail(state, "run-001");
  ensureRunDetail(state, "run-002");

  const { feature, errors, getRenderCount, getLatestModel } = createFeatureHarness(state);
  const deleteRequests: string[] = [];
  mswServer.use(
    ...buildHistoryHandlers({
      list: makeHistoryListPayload({
        runs: [historyListRun("run-002", { status: "analyzing" })],
      }),
      deleteRun: (request) => {
        const url = new URL(request.url);
        deleteRequests.push(url.pathname);
        if (url.pathname === "/api/history/run-001") {
          return makeDeleteHistoryRunPayload({ run_id: "run-001" });
        }
        if (url.pathname === "/api/history/run-002") {
          return { detail: "delete failed", status: 500 };
        }
        return { detail: `Unexpected request: ${url.pathname}`, status: 500 };
      },
    }),
  );

  await feature.deleteAllRuns();

  expect(deleteRequests).toEqual(["/api/history/run-001", "/api/history/run-002"]);
  expect(state.history.deleteAllRunsInFlight.value).toBe(false);
  expect(state.history.expandedRunId.value).toBeNull();
  expect(getRenderCount()).toBeGreaterThanOrEqual(2);
  expect(errors).toHaveLength(1);
  expect(errors[0]).toContain("history.delete_all_partial");
  expect(errors[0]).toContain("delete failed");
  expect(getLatestModel()?.table?.kind).toBe("rows");
});
