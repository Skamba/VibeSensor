import {
  deleteHistoryRun as deleteHistoryRunApi,
  getHistory,
  getHistoryInsights,
  historyExportUrl,
  historyReportPdfUrl,
} from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../ui_app_state";
import type {
  HistoryPanelRenderModel,
  HistoryPanelView,
  HistoryRunAction,
} from "../views/history_table_view";
import { downloadBlobFile } from "./history_download";

export interface HistoryFeatureDeps extends FeatureDepsBase {
  panel: HistoryPanelView;
  navigation: {
    activatePrimaryView(viewId: string): void;
  };
  history: HistoryState;
  getLanguage: () => string;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
}

export interface HistoryFeature {
  bindHandlers(): void;
  renderHistoryTable(): void;
  refreshHistory(): Promise<void>;
  deleteAllRuns(): Promise<void>;
  onHistoryTableAction(action: HistoryRunAction, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
  reloadExpandedRunOnLanguageChange(): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { history, panel } = ctx;
  let handlersBound = false;
  let previewPrefetchToken = 0;

  function activatePrimaryView(viewId: string): void {
    ctx.navigation.activatePrimaryView(viewId);
  }

  function ensureRunDetail(runId: string): RunDetail {
    if (!history.runDetailsById[runId]) {
      history.runDetailsById[runId] = {
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
    return history.runDetailsById[runId];
  }

  function collapseExpandedRun(): void {
    const previous = history.expandedRunId;
    history.expandedRunId = null;
    if (previous) {
      delete history.runDetailsById[previous];
    }
  }

  function buildPanelRenderModel(): HistoryPanelRenderModel {
    const deleteAllRunsDisabled = history.deleteAllRunsInFlight || history.runs.length === 0;
    if (!history.runs.length) {
      collapseExpandedRun();
      return {
        historySummaryText: ctx.t("history.none"),
        deleteAllRunsDisabled,
        table: {
          kind: "empty",
          t: ctx.t,
        },
      };
    }
    if (history.expandedRunId && !history.runs.some((row) => row.run_id === history.expandedRunId)) {
      collapseExpandedRun();
    }
    for (const run of history.runs) {
      ensureRunDetail(run.run_id);
    }
    return {
      historySummaryText: ctx.t("history.available_count", { count: history.runs.length }),
      deleteAllRunsDisabled,
      table: {
        kind: "rows",
        params: {
          runs: history.runs,
          expandedRunId: history.expandedRunId,
          runDetailsById: history.runDetailsById,
          t: ctx.t,
          fmt: ctx.fmt,
          fmtTs: ctx.fmtTs,
          formatInt: ctx.formatInt,
          historyExportUrl,
        },
      },
    };
  }

  function renderHistoryTable(): void {
    panel.setModel(buildPanelRenderModel());
  }

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) {
      return;
    }
    const detail = ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) {
      return;
    }
    detail.previewLoading = true;
    detail.previewError = "";
    renderHistoryTable();
    try {
      const response = await getHistoryInsights(runId, ctx.getLanguage());
      detail.preview = response.status === "complete" ? response : null;
    } catch (err) {
      detail.previewError = err instanceof Error ? err.message : ctx.t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
      renderHistoryTable();
    }
  }

  async function loadRunInsights(runId: string, force = false): Promise<void> {
    if (!runId) {
      return;
    }
    const detail = ensureRunDetail(runId);
    if (!force && detail.insightsLoading) {
      return;
    }
    detail.insightsLoading = true;
    detail.insightsError = "";
    renderHistoryTable();
    try {
      const response = await getHistoryInsights(runId, ctx.getLanguage());
      detail.insights = response.status === "complete" ? response : null;
    } catch (err) {
      detail.insightsError = err instanceof Error ? err.message : ctx.t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      renderHistoryTable();
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) {
      return;
    }
    if (history.expandedRunId === runId) {
      collapseExpandedRun();
      renderHistoryTable();
      return;
    }
    collapseExpandedRun();
    history.expandedRunId = runId;
    renderHistoryTable();
    void loadRunPreview(runId);
  }

  function reloadExpandedRunOnLanguageChange(): void {
    if (!history.expandedRunId) {
      return;
    }
    const runId = history.expandedRunId;
    const detail = history.runDetailsById[runId];
    const shouldReloadInsights = Boolean(detail?.insights);
    delete history.runDetailsById[runId];
    void loadRunPreview(runId, true).then(() => {
      if (shouldReloadInsights) {
        void loadRunInsights(runId, true);
      }
    });
  }

  function prefetchCollapsedRunContext(): void {
    const token = ++previewPrefetchToken;
    void (async () => {
      for (const run of history.runs) {
        if (token !== previewPrefetchToken) {
          return;
        }
        if (run.status !== "complete") {
          continue;
        }
        await loadRunPreview(run.run_id);
      }
    })();
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await getHistory();
      history.runs = payload.runs ?? [];
    } catch (_err) {
      renderHistoryTable();
      return;
    }
    renderHistoryTable();
    prefetchCollapsedRunContext();
  }

  async function deleteRun(runId: string): Promise<void> {
    if (!runId) {
      return;
    }
    const ok = window.confirm(ctx.t("history.delete_confirm", { name: runId }));
    if (!ok) {
      return;
    }
    try {
      await deleteHistoryRunApi(runId);
    } catch (err) {
      ctx.showError(err instanceof Error ? err.message : ctx.t("history.delete_failed"));
      return;
    }
    if (history.expandedRunId === runId) {
      collapseExpandedRun();
    }
    await refreshHistory();
  }

  async function deleteAllRuns(): Promise<void> {
    const names = history.runs.map((row) => row.run_id).filter(Boolean);
    if (!names.length) {
      return;
    }
    const ok = window.confirm(ctx.t("history.delete_all_confirm", { count: names.length }));
    if (!ok) {
      return;
    }

    history.deleteAllRunsInFlight = true;
    renderHistoryTable();
    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const name of names) {
      try {
        await deleteHistoryRunApi(name);
        deleted += 1;
        delete history.runDetailsById[name];
        if (history.expandedRunId === name) {
          collapseExpandedRun();
        }
      } catch (err) {
        failed += 1;
        if (!firstError) {
          firstError = err instanceof Error ? err.message : ctx.t("history.delete_failed");
        }
      }
    }
    history.deleteAllRunsInFlight = false;
    await refreshHistory();
    if (failed > 0) {
      const summary = ctx.t("history.delete_all_partial", { deleted, total: names.length, failed });
      ctx.showError(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function downloadReportPdfForRun(runId: string): Promise<void> {
    const detail = ensureRunDetail(runId);
    if (detail.pdfLoading) {
      return;
    }
    detail.pdfLoading = true;
    detail.pdfError = "";
    renderHistoryTable();
    try {
      await downloadBlobFile(historyReportPdfUrl(runId, ctx.getLanguage()), `${runId}_report.pdf`);
    } catch (err) {
      detail.pdfError = err instanceof Error ? err.message : ctx.t("history.pdf_failed");
    } finally {
      detail.pdfLoading = false;
      renderHistoryTable();
    }
  }

  async function onHistoryTableAction(action: HistoryRunAction, runId: string): Promise<void> {
    if (!action || !runId) {
      return;
    }
    if (action === "download-pdf") {
      await downloadReportPdfForRun(runId);
      return;
    }
    if (action === "delete-run") {
      await deleteRun(runId);
      return;
    }
    if (action === "load-insights") {
      await loadRunInsights(runId, true);
    }
  }

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    panel.bindActions({
      onRefreshHistory: () => {
        void refreshHistory();
      },
      onDeleteAllRuns: () => {
        void deleteAllRuns();
      },
      onTableInteraction: (action) => {
        if (action.type === "open-live") {
          activatePrimaryView("dashboardView");
          return;
        }
        if (action.type === "run-action") {
          void onHistoryTableAction(action.action, action.runId ?? history.expandedRunId ?? "");
          return;
        }
        toggleRunDetails(action.runId);
      },
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
