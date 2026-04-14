import { expect, test } from "@playwright/test";

import { createHistoryFeature } from "../src/app/features/history_feature";
import { createHistoryDetailModule } from "../src/app/features/history_detail_module";
import {
  createHistoryDownloadDeleteModule,
  downloadBlobFile,
} from "../src/app/features/history_download_delete_module";
import { createHistoryListModule } from "../src/app/features/history_list_module";
import type { UiHistoryDom } from "../src/app/dom/history_dom";
import type { UiShellDom } from "../src/app/dom/shell_dom";
import { createAppState, type RunDetail } from "../src/app/ui_app_state";
import {
  renderHistoryEmptyState,
  renderHistoryTable,
  type HistoryPanelActionHandlers,
  type HistoryPanelView,
} from "../src/app/views/history_table_view";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";
import {
  findByAttribute,
  findByClass,
  installFakeDomGlobals,
  type FakeElement,
  FakeHTMLElement,
} from "./dom_render_test_support";

type ButtonStub = HTMLButtonElement & {
  disabled: boolean;
};

let restoreDom = () => undefined;

function createButton(): ButtonStub {
  return {
    disabled: false,
    addEventListener() {
      /* no-op */
    },
  } as unknown as ButtonStub;
}

function createTextElement(tagName = "DIV"): HTMLElement {
  return new FakeHTMLElement(tagName) as unknown as HTMLElement;
}

function createHistoryElements(): {
  dom: UiHistoryDom;
  panel: HistoryPanelView;
  historySummary: FakeElement;
  historyTableBody: FakeElement;
  deleteAllRunsBtn: ButtonStub;
} {
  const historySummary = createTextElement("DIV") as unknown as FakeElement;
  const historyTableBody = createTextElement("TBODY") as unknown as FakeElement;
  const deleteAllRunsBtn = createButton();
  let actions: HistoryPanelActionHandlers | null = null;
  const panel: HistoryPanelView = {
    render(model) {
      historySummary.textContent = model.historySummaryText;
      deleteAllRunsBtn.disabled = model.deleteAllRunsDisabled;
      if (model.table === null) {
        historyTableBody.textContent = "No runs found.";
        return;
      }
      if (model.table.kind === "empty") {
        renderHistoryEmptyState(historyTableBody as unknown as HTMLElement, {
          t: model.table.t,
        });
        return;
      }
      renderHistoryTable(historyTableBody as unknown as HTMLElement, model.table.params);
    },
    bindActions(handlers) {
      actions = handlers;
    },
  };
  void actions;
  const dom = {} as UiHistoryDom;
  return {
    dom,
    panel,
    historySummary,
    historyTableBody,
    deleteAllRunsBtn,
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

function historyListRun(runId: string) {
  return {
    run_id: runId,
    status: "complete" as const,
    start_time_utc: "2026-01-01T00:00:00Z",
    end_time_utc: "2026-01-01T00:00:12Z",
    created_at: "2026-01-01T00:00:00Z",
    sample_count: 42,
    car_name: "Track Car",
    error_message: null,
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

function expectSingleByClass(root: FakeElement, className: string): FakeElement {
  const matches = findByClass(root, className);
  expect(matches, `Expected exactly one .${className} element`).toHaveLength(1);
  return matches[0];
}

function expectSingleByAttribute(
  root: FakeElement,
  attributeName: string,
  expectedValue: string,
): FakeElement {
  const matches = findByAttribute(root, attributeName, expectedValue);
  expect(matches, `Expected exactly one [${attributeName}="${expectedValue}"] element`).toHaveLength(1);
  return matches[0];
}

test.beforeEach(() => {
  installWindowGlobal();
  restoreDom = installFakeDomGlobals();
});

test.afterEach(() => {
  restoreDom();
  restoreDom = () => undefined;
});

test("history list module refreshes runs and renders table state", async () => {
  const state = createAppState();
  const { panel, historySummary, historyTableBody, deleteAllRunsBtn } = createHistoryElements();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (url === "/api/history") {
      return jsonResponse({
        runs: [historyListRun("run-001")],
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  const module = createHistoryListModule({
    history: state.history,
    panel,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
    ensureRunDetail: (runId) => ensureRunDetail(state, runId),
    collapseExpandedRun: () => {
      state.history.expandedRunId = null;
    },
  });

  try {
    await module.refreshHistory();
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(state.history.runs).toHaveLength(1);
  expect(historySummary.textContent).toContain("history.available_count");
  const row = expectSingleByAttribute(historyTableBody, "data-run-row", "1");
  const toggle = expectSingleByAttribute(row, "data-run-toggle", "details");
  const summaryChips = findByClass(row, "history-row__summary-chip").map((chip) => chip.textContent);
  expect(row.getAttribute("data-run")).toBe("run-001");
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(summaryChips).toContain("history.row_status.complete");
  expect(summaryChips.some((chip) => chip.includes("history.summary_size"))).toBe(true);
  expect(row.textContent).toContain("Track Car");
  expect(row.textContent).toContain("history.car_label");
  expect(toggle.textContent).toContain("history.preview_available");
  expect(toggle.textContent).toContain("history.open_diagnosis");
  expect(findByAttribute(historyTableBody, "data-run-action", "delete-run")).toHaveLength(0);
  expect(deleteAllRunsBtn.disabled).toBe(false);
});

test("history detail module loads preview and reloads expanded run on language change", async () => {
  const state = createAppState();
  state.history.expandedRunId = null;
  createHistoryElements();
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

  let renderCalls = 0;
  const module = createHistoryDetailModule({
    history: state.history,
    getLanguage: () => state.shell.lang,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    ensureRunDetail: (runId) => ensureRunDetail(state, runId),
    collapseExpandedRun: () => {
      const previous = state.history.expandedRunId;
      state.history.expandedRunId = null;
      if (previous) {
        delete state.history.runDetailsById[previous];
      }
    },
    renderHistoryTable: () => {
      renderCalls += 1;
    },
  });

  try {
    module.toggleRunDetails("run-001");
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(1);
    await module.loadRunInsights("run-001", true);
    expect(state.history.runDetailsById["run-001"]?.insights?.sensor_count_used).toBe(1);

    state.shell.lang = "nl";
    module.reloadExpandedRunOnLanguageChange();
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);
    await expect.poll(() => state.history.runDetailsById["run-001"]?.insights?.sensor_count_used ?? null).toBe(2);
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(renderCalls).toBeGreaterThanOrEqual(6);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=nl",
    "/api/history/run-001/insights?lang=nl",
  ]);
});

test("history detail module treats analyzing insights responses as not-yet-available", async () => {
  const state = createAppState();
  createHistoryElements();
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

  let renderCalls = 0;
  const module = createHistoryDetailModule({
    history: state.history,
    getLanguage: () => state.shell.lang,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    ensureRunDetail: (runId) => ensureRunDetail(state, runId),
    collapseExpandedRun: () => {
      state.history.expandedRunId = null;
    },
    renderHistoryTable: () => {
      renderCalls += 1;
    },
  });

  try {
    await module.loadRunPreview("run-001");
    await module.loadRunInsights("run-001", true);
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(state.history.runDetailsById["run-001"]?.preview).toBeNull();
  expect(state.history.runDetailsById["run-001"]?.previewError).toBe("");
  expect(state.history.runDetailsById["run-001"]?.insights).toBeNull();
  expect(state.history.runDetailsById["run-001"]?.insightsError).toBe("");
  expect(renderCalls).toBeGreaterThanOrEqual(4);
  expect(requests).toEqual([
    "/api/history/run-001/insights?lang=en",
    "/api/history/run-001/insights?lang=en",
  ]);
});

test("history list rendering promotes loaded findings ahead of supporting statistics", () => {
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
  const { panel, historyTableBody } = createHistoryElements();

  const module = createHistoryListModule({
    history: state.history,
    panel,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
    ensureRunDetail: (runId) => ensureRunDetail(state, runId),
    collapseExpandedRun: () => {
      state.history.expandedRunId = null;
    },
  });

  module.renderHistoryTable();

  expect(expectSingleByClass(historyTableBody, "history-details-header__eyebrow").textContent)
    .toBe("history.details_title");
  expect(expectSingleByClass(historyTableBody, "history-findings-overview__eyebrow").textContent)
    .toBe("history.primary_diagnosis");
  expect(findByClass(historyTableBody, "history-evidence-column")).toHaveLength(1);
  expect(expectSingleByAttribute(historyTableBody, "data-location-key", "front-right wheel").textContent)
    .toContain("32.0 dB");
  expect(expectSingleByClass(historyTableBody, "history-findings-overview__headline").textContent)
    .toBe("Front-right wheel imbalance");
  expect(findByClass(historyTableBody, "history-findings-chip__label").map((label) => label.textContent))
    .toContain("history.findings_signature");
  expect(expectSingleByClass(historyTableBody, "history-secondary-findings__title").textContent)
    .toBe("history.secondary_candidates_title");
  expect(historyTableBody.textContent).not.toContain("history.findings_loaded");
  expect(findByClass(historyTableBody, "history-finding-card__title").map((title) => title.textContent))
    .toContain("Secondary driveline contribution");
  expect(historyTableBody.textContent).not.toContain("history.preview_stats_title");
  expect(expectSingleByClass(historyTableBody, "history-diagnosis-card__next-step-label").textContent)
    .toBe("history.findings_next_step_label");
  expect(expectSingleByClass(historyTableBody, "history-details-footer__eyebrow").textContent)
    .toBe("history.run_actions_title");
  expect(findByAttribute(historyTableBody, "data-run-action", "delete-run")).toHaveLength(1);
});

test("history feature preloads collapsed row context for completed runs", async () => {
  const state = createAppState();
  const { dom, panel, historyTableBody } = createHistoryElements();
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

  const feature = createHistoryFeature({
    dom,
    panel,
    shellDom: { menuButtons: [] } as Pick<UiShellDom, "menuButtons">,
    history: state.history,
    getLanguage: () => state.shell.lang,
    t: testTranslation,
    escapeHtml: (value) => String(value ?? ""),
    showError: () => {
      /* no-op */
    },
    fmt: (value, digits = 0) => Number(value).toFixed(digits),
    fmtTs: (iso) => iso,
    formatInt: (value) => String(value),
  });

  try {
    await feature.refreshHistory();
    await expect.poll(() => state.history.runDetailsById["run-001"]?.preview?.sensor_count_used ?? null).toBe(2);
  } finally {
    globalThis.fetch = originalFetch;
  }

  const summaryChips = findByClass(historyTableBody, "history-row__summary-chip").map((chip) => chip.textContent);
  expect(summaryChips).toContain("Front-right wheel imbalance");
  expect(summaryChips.some((chip) => chip.includes("report.confidence"))).toBe(true);
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

test("history download/delete module reports partial delete failures without detail-loading deps", async () => {
  const state = createAppState();
  state.history.runs = [
    { run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 },
    { run_id: "run-002", start_time_utc: "2026-01-01T00:10:00Z", sample_count: 84 },
  ];
  state.history.expandedRunId = "run-001";
  ensureRunDetail(state, "run-001");
  ensureRunDetail(state, "run-002");

  const originalFetch = globalThis.fetch;
  const originalConfirm = window.confirm;
  const deleteRequests: string[] = [];
  const errors: string[] = [];

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
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;
  window.confirm = (() => true) as typeof window.confirm;

  let renderCalls = 0;
  let refreshCalls = 0;
  const module = createHistoryDownloadDeleteModule({
    history: state.history,
    getLanguage: () => state.shell.lang,
    t: testTranslation,
    showError: (message) => {
      errors.push(message);
    },
    ensureRunDetail: (runId) => ensureRunDetail(state, runId),
    collapseExpandedRun: () => {
      const previous = state.history.expandedRunId;
      state.history.expandedRunId = null;
      if (previous) {
        delete state.history.runDetailsById[previous];
      }
    },
    renderHistoryTable: () => {
      renderCalls += 1;
    },
    refreshHistory: async () => {
      refreshCalls += 1;
    },
    loadRunInsights: async () => {
      throw new Error("should not be called");
    },
  });

  try {
    await module.deleteAllRuns();
  } finally {
    globalThis.fetch = originalFetch;
    window.confirm = originalConfirm;
  }

  expect(deleteRequests).toEqual(["/api/history/run-001", "/api/history/run-002"]);
  expect(state.history.deleteAllRunsInFlight).toBe(false);
  expect(state.history.expandedRunId).toBeNull();
  expect(renderCalls).toBe(1);
  expect(refreshCalls).toBe(1);
  expect(errors).toHaveLength(1);
  expect(errors[0]).toContain("history.delete_all_partial");
  expect(errors[0]).toContain("delete failed");
});
