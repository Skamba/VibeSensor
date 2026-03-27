import { expect, test } from "@playwright/test";

import { createHistoryDetailModule } from "../src/app/features/history_detail_module";
import {
  createHistoryDownloadDeleteModule,
  downloadBlobFile,
} from "../src/app/features/history_download_delete_module";
import { createHistoryListModule } from "../src/app/features/history_list_module";
import { createAppState, type RunDetail } from "../src/app/ui_app_state";
import type { UiDomElements } from "../src/app/ui_dom_registry";
import { installWindowGlobal, jsonResponse } from "./async_test_helpers";

type ButtonStub = HTMLButtonElement & {
  disabled: boolean;
};

type TextElementStub = HTMLElement & {
  innerHTML: string;
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

function createTextElement(): TextElementStub {
  return {
    innerHTML: "",
    textContent: "",
    addEventListener() {
      /* no-op */
    },
  } as unknown as TextElementStub;
}

function createHistoryElements(): {
  els: UiDomElements;
  historySummary: TextElementStub;
  historyTableBody: TextElementStub;
  deleteAllRunsBtn: ButtonStub;
} {
  const historySummary = createTextElement();
  const historyTableBody = createTextElement();
  const deleteAllRunsBtn = createButton();
  return {
    els: {
      historySummary,
      historyTableBody,
      deleteAllRunsBtn,
    } as unknown as UiDomElements,
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

function historyInsightsAnalyzingPayload(runId: string) {
  return {
    run_id: runId,
    status: "analyzing" as const,
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

test.beforeEach(() => {
  installWindowGlobal();
});

test("history list module refreshes runs and renders table state", async () => {
  const state = createAppState();
  const { els, historySummary, historyTableBody, deleteAllRunsBtn } = createHistoryElements();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input: string | URL | RequestInfo) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input : input.url);
    if (url === "/api/history") {
      return jsonResponse({
        runs: [{ run_id: "run-001", start_time_utc: "2026-01-01T00:00:00Z", sample_count: 42 }],
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  }) as typeof fetch;

  const module = createHistoryListModule({
    history: state.history,
    els,
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
  expect(historyTableBody.innerHTML).toContain("run-001");
  expect(historyTableBody.innerHTML).toContain('data-run-toggle="details"');
  expect(historyTableBody.innerHTML).toContain('aria-expanded="false"');
  expect(historyTableBody.innerHTML).toContain("history.preview_available");
  expect(deleteAllRunsBtn.disabled).toBe(false);
});

test("history detail module loads preview and reloads expanded run on language change", async () => {
  const state = createAppState();
  state.history.expandedRunId = null;
  const { els } = createHistoryElements();
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
    els,
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
  const { els } = createHistoryElements();
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
    els,
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
