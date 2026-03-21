import type { FeatureDepsBase } from "../feature_deps_base";
import type { AppState, RunDetail } from "../ui_app_state";
import type { HistoryInsightsPayload } from "../../api/types";
import {
  deleteHistoryRun as deleteHistoryRunApi,
  getHistory,
  getHistoryInsights,
  historyExportUrl,
  historyReportPdfUrl,
} from "../../api";
import {
  getHistoryTableAction,
  getHistoryTableRowRunId,
  renderHistoryEmptyState,
  renderHistoryTable as renderHistoryTableView,
} from "../views/history_table_view";

export interface HistoryFeatureDeps extends FeatureDepsBase {
  state: AppState;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

export interface HistoryFeature {
  bindHandlers(): void;
  renderHistoryTable(): void;
  refreshHistory(): Promise<void>;
  deleteAllRuns(): Promise<void>;
  onHistoryTableAction(action: string, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
  reloadExpandedRunOnLanguageChange(): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { state, els, t, escapeHtml, fmt, fmtTs, formatInt } = ctx;
  const DOWNLOAD_REVOKE_DELAY_MS = 1000;
  let handlersBound = false;

  function ensureRunDetail(runId: string): RunDetail {
    if (!state.runDetailsById[runId]) {
      state.runDetailsById[runId] = {
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
    return state.runDetailsById[runId];
  }

  function collapseExpandedRun(): void {
    const previous = state.expandedRunId;
    state.expandedRunId = null;
    if (previous) {
      delete state.runDetailsById[previous];
    }
  }

  function renderHistoryTable(): void {
    if (els.deleteAllRunsBtn) {
      els.deleteAllRunsBtn.disabled = state.deleteAllRunsInFlight || state.runs.length === 0;
    }
    if (!state.runs.length) {
      if (els.historySummary) {
        els.historySummary.textContent = t("history.none");
      }
      if (els.historyTableBody) {
        renderHistoryEmptyState(els.historyTableBody, escapeHtml(t("history.none_found")));
      }
      collapseExpandedRun();
      return;
    }
    if (state.expandedRunId && !state.runs.some((row) => row.run_id === state.expandedRunId)) {
      collapseExpandedRun();
    }
    if (els.historySummary) {
      els.historySummary.textContent = t("history.available_count", { count: state.runs.length });
    }
    for (const run of state.runs) {
      ensureRunDetail(run.run_id);
    }
    if (els.historyTableBody) {
      renderHistoryTableView(els.historyTableBody, {
        runs: state.runs,
        expandedRunId: state.expandedRunId,
        runDetailsById: state.runDetailsById,
        t,
        escapeHtml,
        fmt,
        fmtTs,
        formatInt,
        historyExportUrl,
      });
    }
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await getHistory();
      state.runs = payload.runs ?? [];
      renderHistoryTable();
    } catch (_err) {
      renderHistoryTable();
    }
  }

  async function deleteRun(runId: string): Promise<void> {
    if (!runId) return;
    const ok = window.confirm(t("history.delete_confirm", { name: runId }));
    if (!ok) return;
    try {
      await deleteHistoryRunApi(runId);
    } catch (err) {
      window.alert(err instanceof Error ? err.message : t("history.delete_failed"));
      return;
    }
    if (state.expandedRunId === runId) {
      collapseExpandedRun();
    }
    await refreshHistory();
  }

  async function deleteAllRuns(): Promise<void> {
    const names = state.runs.map((row) => row.run_id).filter(Boolean);
    if (!names.length) return;
    const ok = window.confirm(t("history.delete_all_confirm", { count: names.length }));
    if (!ok) return;

    state.deleteAllRunsInFlight = true;
    renderHistoryTable();
    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const name of names) {
      try {
        await deleteHistoryRunApi(name);
        deleted += 1;
        delete state.runDetailsById[name];
        if (state.expandedRunId === name) {
          collapseExpandedRun();
        }
      } catch (err) {
        failed += 1;
        if (!firstError) {
          firstError = err instanceof Error ? err.message : t("history.delete_failed");
        }
      }
    }
    state.deleteAllRunsInFlight = false;
    await refreshHistory();
    if (failed > 0) {
      const summary = t("history.delete_all_partial", { deleted, total: names.length, failed });
      window.alert(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) return;
    detail.previewLoading = true;
    detail.previewError = "";
    renderHistoryTable();
    try {
      detail.preview = await getHistoryInsights(runId, state.lang);
    } catch (err) {
      detail.previewError = err instanceof Error ? err.message : t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
      renderHistoryTable();
    }
  }

  async function loadRunInsights(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ensureRunDetail(runId);
    if (!force && detail.insightsLoading) return;
    detail.insightsLoading = true;
    detail.insightsError = "";
    renderHistoryTable();
    try {
      detail.insights = await getHistoryInsights(runId, state.lang);
    } catch (err) {
      detail.insightsError = err instanceof Error ? err.message : t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      renderHistoryTable();
    }
  }

  function filenameFromDisposition(headerValue: string | null, fallback: string): string {
    if (!headerValue) return fallback;
    const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
      try {
        return decodeURIComponent(utf8Match[1]);
      } catch {
        /* fall through to simple match */
      }
    }
    const simpleMatch = headerValue.match(/filename="?([^";]+)"?/i);
    if (simpleMatch && simpleMatch[1]) return simpleMatch[1];
    return fallback;
  }

  async function downloadBlobFile(url: string, fallbackName: string): Promise<void> {
    const response = await fetch(url);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (payload && typeof payload.detail === "string") detail = payload.detail;
      } catch (_err) {
        /* ignore */
      }
      throw new Error(detail);
    }
    const blob = await response.blob();
    const fileName = filenameFromDisposition(
      response.headers.get("content-disposition"),
      fallbackName || "download.bin",
    );
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), DOWNLOAD_REVOKE_DELAY_MS);
  }

  async function downloadReportPdfForRun(runId: string): Promise<void> {
    const detail = ensureRunDetail(runId);
    if (detail.pdfLoading) return;
    detail.pdfLoading = true;
    detail.pdfError = "";
    renderHistoryTable();
    try {
      await downloadBlobFile(historyReportPdfUrl(runId, state.lang), `${runId}_report.pdf`);
    } catch (err) {
      detail.pdfError = err instanceof Error ? err.message : t("history.pdf_failed");
    } finally {
      detail.pdfLoading = false;
      renderHistoryTable();
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) return;
    if (state.expandedRunId === runId) {
      collapseExpandedRun();
      renderHistoryTable();
      return;
    }
    collapseExpandedRun();
    state.expandedRunId = runId;
    renderHistoryTable();
    void loadRunPreview(runId);
  }

  async function onHistoryTableAction(action: string, runId: string): Promise<void> {
    if (!action || !runId) return;
    if (action === "download-pdf") return downloadReportPdfForRun(runId);
    if (action === "delete-run") return deleteRun(runId);
    if (action === "load-insights") {
      await loadRunInsights(runId, true);
    }
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    els.refreshHistoryBtn?.addEventListener("click", () => void refreshHistory());
    els.deleteAllRunsBtn?.addEventListener("click", () => void deleteAllRuns());
    els.historyTableBody?.addEventListener("click", (event) => {
      const action = getHistoryTableAction(event.target);
      if (action) {
        if (action.action !== "download-raw") {
          event.preventDefault();
        }
        event.stopPropagation();
        void onHistoryTableAction(action.action, action.runId ?? state.expandedRunId ?? "");
        return;
      }
      const runId = getHistoryTableRowRunId(event.target);
      if (runId) {
        toggleRunDetails(runId);
      }
    });
  }

  function reloadExpandedRunOnLanguageChange(): void {
    if (!state.expandedRunId) return;
    const runId = state.expandedRunId;
    const detail = state.runDetailsById[runId];
    const shouldReloadInsights = Boolean(detail?.insights);
    delete state.runDetailsById[runId];
    void loadRunPreview(runId, true).then(() => {
      if (shouldReloadInsights) {
        void loadRunInsights(runId, true);
      }
    });
  }

  return {
    bindHandlers,
    renderHistoryTable,
    refreshHistory,
    deleteAllRuns,
    onHistoryTableAction,
    toggleRunDetails,
    reloadExpandedRunOnLanguageChange,
  };
}
