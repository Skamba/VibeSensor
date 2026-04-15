import { expect, test } from "@playwright/test";

import { createHistoryFeature } from "../src/app/features/history_feature";
import { downloadBlobFile } from "../src/app/features/history_download";
import { createAppState, type RunDetail } from "../src/app/ui_app_state";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "../src/app/views/history_table_view";
import { buildHistoryTableRowsViewModel } from "../src/app/views/history_table_presenters";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";

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
    setModel(model) {
      renderCount += 1;
      latestModel = model;
      historySummary.textContent = model.historySummaryText;
      deleteAllRunsBtn.disabled = model.deleteAllRunsDisabled;
    },
    bindActions(handlers) {
      latestHandlers = handlers;
    },
  };
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
  if (!state.history.runDetailsById[runId]) {
    state.history.runDetailsById[runId] = {
      preview: null,
      previewLoading: false,
      previewError: "",
      insights: null,
      insightsLoading: false,
      insightsError: "",
      pdfLoading: false,
      pdfError: "",
    };
  }
  return state.history.runDetailsById[runId];
}

function latestRowModels(panel: { getLatestModel(): HistoryPanelRenderModel | null }) {
  const model = panel.getLatestModel();
  expect(model?.table?.kind).toBe("rows");
  if (!model || !model.table || model.table.kind !== "rows") {
    throw new Error("Expected rendered history rows");
  }
  return buildHistoryTableRowsViewModel(model.table.params);
}

function createFeatureHarness(
  state = createAppState(),
  overrides: {
    panel?: HistoryPanelView;
    showError?: (message: string) => void;
    activatePrimaryView?: (viewId: string) => void;
  } = {},
) {
  const panelElements = createHistoryElements();
  const errors: string[] = [];
  const primaryViewActivations: string[] = [];
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
    getLanguage: () => state.shell.lang,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    showError: overrides.showError ?? ((message) => {
      errors.push(message);
    }),
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });
  return {
    feature,
    state,
    errors,
    primaryViewActivations,
    ...panelElements,
  };
}

test.beforeEach(() => {
  installWindowGlobal();
});

test("history feature refreshes runs and renders an empty-state model when no runs exist", async () => {
  const { feature, historySummary, deleteAllRunsBtn, getLatestModel } = createFeatureHarness();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (url === "/api/history") {
      return jsonResponse({ runs: [] });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  try {
    await feature.refreshHistory();
  } finally {
    globalThis.fetch = originalFetch;
  }

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
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (url === "/api/history") {
      return jsonResponse({
        runs: [historyListRun("run-001", { status: "analyzing" })],
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  try {
    await feature.refreshHistory();
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(state.history.runs).toHaveLength(1);
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

test("history feature binds panel actions through the shared owner", () => {
  const { feature, getLatestHandlers, primaryViewActivations } = createFeatureHarness();
  feature.bindHandlers();

  const handlers = getLatestHandlers();
  expect(handlers).not.toBeNull();
  handlers?.onTableInteraction({ type: "open-live" });

  expect(primaryViewActivations).toEqual(["dashboardView"]);
});

test("history feature loads preview and reloads expanded run on language change", async () => {
  const state = createAppState();
  state.history.runs = [historyListRun("run-001")];
  const { feature, getRenderCount } = createFeatureHarness(state);
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    requests.push(url);
    if (url === "/api/history/run-001/insights?lang=en") {
      return jsonResponse(historyInsightsPayload("run-001", 1));
    }
    if (url === "/api/history/run-001/insights?lang=nl") {
      return jsonResponse(historyInsightsPayload("run-001", 2));
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  try {
    feature.toggleRunDetails("run-001");
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(1);
    await feature.onHistoryTableAction("load-insights", "run-001");
    expect(state.history.runDetailsById["run-001"]?.insights?.sensor_count_used).toBe(1);

    state.shell.lang = "nl";
    feature.reloadExpandedRunOnLanguageChange();
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);
    await expect.poll(() => state.history.runDetailsById["run-001"]?.insights?.sensor_count_used ?? null).toBe(2);
  } finally {
    globalThis.fetch = originalFetch;
  }

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
  state.history.runs = [historyListRun("run-001")];
  const { feature, getRenderCount } = createFeatureHarness(state);
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    requests.push(url);
    if (url === "/api/history/run-001/insights?lang=en") {
      return jsonResponse(historyInsightsAnalyzingPayload("run-001"), { status: 202 });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  try {
    feature.toggleRunDetails("run-001");
    await expect.poll(() => state.history.runDetailsById["run-001"]?.previewLoading ?? false).toBe(false);
    await feature.onHistoryTableAction("load-insights", "run-001");
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(state.history.runDetailsById["run-001"]?.preview).toBeNull();
  expect(state.history.runDetailsById["run-001"]?.previewError).toBe("");
  expect(state.history.runDetailsById["run-001"]?.insights).toBeNull();
  expect(state.history.runDetailsById["run-001"]?.insightsError).toBe("");
  expect(getRenderCount()).toBeGreaterThanOrEqual(4);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
  ]);
});

test("history feature rendering promotes loaded findings ahead of supporting statistics", () => {
  const state = createAppState();
  state.history.runs = [historyListRun("run-001")];
  state.history.expandedRunId = "run-001";
  state.history.runDetailsById["run-001"] = {
    preview: historyInsightsWithFindingsPayload("run-001", 2) as RunDetail["preview"],
    previewLoading: false,
    previewError: "",
    insights: historyInsightsWithFindingsPayload("run-001", 2) as RunDetail["insights"],
    insightsLoading: false,
    insightsError: "",
    pdfLoading: false,
    pdfError: "",
  };
  const { feature, getLatestModel } = createFeatureHarness(state);

  feature.renderHistoryTable();

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
  const originalFetch = globalThis.fetch;
  const requests: string[] = [];
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    requests.push(url);
    if (url === "/api/history") {
      return jsonResponse({ runs: [historyListRun("run-001")] });
    }
    if (url === "/api/history/run-001/insights?lang=en") {
      return jsonResponse(historyInsightsWithFindingsPayload("run-001", 2));
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  try {
    await feature.refreshHistory();
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);
  } finally {
    globalThis.fetch = originalFetch;
  }

  const row = latestRowModels({ getLatestModel })[0];
  expect(row.summaryChips.map((chip) => chip.text)).toContain("history.row_status.complete");
  expect(row.summaryHeadline).toBe("Front-right wheel imbalance");
  expect(row.summaryMeta?.includes("report.confidence")).toBe(true);
  expect(requests).toEqual([
    "/api/history",
    "/api/history/run-001/insights?lang=en",
  ]);
});

test("downloadBlobFile downloads with decoded filename and revokes the blob URL", async () => {
  const originalFetch = globalThis.fetch;
  const originalDocument = (globalThis as { document?: Document }).document;
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalSetTimeout = globalThis.setTimeout;
  const anchorState = { href: "", download: "", clicks: 0, removed: 0 };
  const revoked: string[] = [];

  globalThis.fetch = (async () => new Response("PDF", {
    status: 200,
    headers: {
      "content-type": "application/pdf",
      "content-disposition": "attachment; filename*=UTF-8''run%20%C3%BC.pdf",
    },
  })) as typeof fetch;
  (globalThis as { document?: Document }).document = {
    body: {
      appendChild() {
        /* no-op */
      },
    } as unknown as HTMLBodyElement,
    createElement(tagName: string) {
      expect(tagName).toBe("a");
      return {
        set href(value: string) {
          anchorState.href = value;
        },
        get href() {
          return anchorState.href;
        },
        set download(value: string) {
          anchorState.download = value;
        },
        get download() {
          return anchorState.download;
        },
        click() {
          anchorState.clicks += 1;
        },
        remove() {
          anchorState.removed += 1;
        },
      } as unknown as HTMLAnchorElement;
    },
  } as Document;
  URL.createObjectURL = (() => "blob:history-download-test") as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((url: string) => {
    revoked.push(url);
  }) as typeof URL.revokeObjectURL;
  globalThis.setTimeout = ((handler: TimerHandler) => {
    if (typeof handler === "function") {
      handler();
    }
    return 0 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;

  try {
    await downloadBlobFile("/api/history/run-001/report.pdf", "fallback.pdf");
  } finally {
    globalThis.fetch = originalFetch;
    (globalThis as { document?: Document }).document = originalDocument;
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    globalThis.setTimeout = originalSetTimeout;
  }

  expect(anchorState.download).toBe("run ü.pdf");
  expect(anchorState.href).toBe("blob:history-download-test");
  expect(anchorState.clicks).toBe(1);
  expect(anchorState.removed).toBe(1);
  expect(revoked).toEqual(["blob:history-download-test"]);
});

test("history feature reports partial delete failures without splitting render ownership", async () => {
  const state = createAppState();
  state.history.runs = [
    historyListRun("run-001"),
    historyListRun("run-002"),
  ];
  state.history.expandedRunId = "run-001";
  ensureRunDetail(state, "run-001");
  ensureRunDetail(state, "run-002");

  const { feature, errors, getRenderCount, getLatestModel } = createFeatureHarness(state);
  const originalFetch = globalThis.fetch;
  const originalConfirm = window.confirm;
  const deleteRequests: string[] = [];

  globalThis.fetch = (async (input: string | URL | RequestInfo, init?: RequestInit) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (init?.method === "DELETE" && url === "/api/history/run-001") {
      deleteRequests.push(url);
      return jsonResponse({ ok: true });
    }
    if (init?.method === "DELETE" && url === "/api/history/run-002") {
      deleteRequests.push(url);
      return jsonResponse({ detail: "delete failed" }, { status: 500 });
    }
    if (url === "/api/history") {
      return jsonResponse({
        runs: [historyListRun("run-002", { status: "analyzing" })],
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;
  window.confirm = (() => true) as typeof window.confirm;

  try {
    await feature.deleteAllRuns();
  } finally {
    globalThis.fetch = originalFetch;
    window.confirm = originalConfirm;
  }

  expect(deleteRequests).toEqual(["/api/history/run-001", "/api/history/run-002"]);
  expect(state.history.deleteAllRunsInFlight).toBe(false);
  expect(state.history.expandedRunId).toBeNull();
  expect(getRenderCount()).toBeGreaterThanOrEqual(2);
  expect(errors).toHaveLength(1);
  expect(errors[0]).toContain("history.delete_all_partial");
  expect(errors[0]).toContain("delete failed");
  expect(getLatestModel()?.table?.kind).toBe("rows");
});
