import {
  deleteHistoryRun as deleteHistoryRunApi,
  getHistory,
  getHistoryInsights,
  historyExportUrl,
  historyReportPdfUrl,
} from "../../api";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import {
  trackAppStateSlice,
  type HistoryState,
  type RunDetail,
  type ShellState,
} from "../ui_app_state";
import { computed, effect, untracked } from "../ui_signals";
import type {
  HistoryPanelRenderModel,
  HistoryPanelView,
  HistoryRunAction,
} from "../views/history_table_view";
import { downloadBlobFile } from "./history_download";

export interface HistoryFeatureDeps {
  panel: HistoryPanelView;
  navigation: {
    activatePrimaryView(viewId: string): void;
  };
  history: HistoryState;
  shell: Pick<ShellState, "lang">;
  services: FeatureServices;
  formatting: FeatureFormatting;
}

export interface HistoryFeature {
  bindHandlers(): void;
  refreshHistory(): Promise<void>;
  deleteAllRuns(): Promise<void>;
  onHistoryTableAction(action: HistoryRunAction, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { history, panel, shell, services, formatting } = ctx;
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
    const expandedRunId = history.expandedRunId
      && history.runs.some((row) => row.run_id === history.expandedRunId)
      ? history.expandedRunId
      : null;
    if (!history.runs.length) {
      return {
        historySummaryText: services.t("history.none"),
        deleteAllRunsDisabled,
        table: {
          kind: "empty",
          t: services.t,
        },
      };
    }
    return {
      historySummaryText: services.t("history.available_count", {
        count: history.runs.length,
      }),
      deleteAllRunsDisabled,
        table: {
          kind: "rows",
          params: {
            runs: history.runs,
            expandedRunId,
            runDetailsById: history.runDetailsById,
            t: services.t,
            fmt: formatting.fmt,
          fmtTs: formatting.fmtTs,
          formatInt: formatting.formatInt,
          historyExportUrl,
        },
      },
      };
  }
  const panelModel = computed(() => {
    trackAppStateSlice(history);
    return buildPanelRenderModel();
  });
  panel.bindModel(panelModel);

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
    try {
      const response = await getHistoryInsights(runId, shell.lang);
      detail.preview = response.status === "complete" ? response : null;
    } catch (err) {
      detail.previewError = err instanceof Error
        ? err.message
        : services.t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
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
    try {
      const response = await getHistoryInsights(runId, shell.lang);
      detail.insights = response.status === "complete" ? response : null;
    } catch (err) {
      detail.insightsError = err instanceof Error
        ? err.message
        : services.t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) {
      return;
    }
    if (history.expandedRunId === runId) {
      collapseExpandedRun();
      return;
    }
    collapseExpandedRun();
    history.expandedRunId = runId;
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

  function bindReactiveLanguageSync(): void {
    let initialized = false;
    let previousLanguage = shell.lang;
    effect(() => {
      const currentLanguage = shell.lang;
      if (!initialized) {
        initialized = true;
        previousLanguage = currentLanguage;
        return;
      }
      if (currentLanguage === previousLanguage) {
        return;
      }
      previousLanguage = currentLanguage;
      untracked(() => {
        reloadExpandedRunOnLanguageChange();
      });
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
      return;
    }
    prefetchCollapsedRunContext();
  }

  async function deleteRun(runId: string): Promise<void> {
    if (!runId) {
      return;
    }
    const ok = await services.requestConfirmation(
      services.t("history.delete_confirm", { name: runId }),
    );
    if (!ok) {
      return;
    }
    try {
      await deleteHistoryRunApi(runId);
    } catch (err) {
      services.showError(
        err instanceof Error ? err.message : services.t("history.delete_failed"),
      );
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
    const ok = await services.requestConfirmation(
      services.t("history.delete_all_confirm", { count: names.length }),
    );
    if (!ok) {
      return;
    }

    history.deleteAllRunsInFlight = true;
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
          firstError = err instanceof Error
            ? err.message
            : services.t("history.delete_failed");
        }
      }
    }
    history.deleteAllRunsInFlight = false;
    await refreshHistory();
    if (failed > 0) {
      const summary = services.t("history.delete_all_partial", {
        deleted,
        total: names.length,
        failed,
      });
      services.showError(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function downloadReportPdfForRun(runId: string): Promise<void> {
    const detail = ensureRunDetail(runId);
    if (detail.pdfLoading) {
      return;
    }
    detail.pdfLoading = true;
    detail.pdfError = "";
    try {
      await downloadBlobFile(
        historyReportPdfUrl(runId, shell.lang),
        `${runId}_report.pdf`,
      );
    } catch (err) {
      detail.pdfError = err instanceof Error
        ? err.message
        : services.t("history.pdf_failed");
    } finally {
      detail.pdfLoading = false;
    }
  }

  async function onHistoryTableAction(
    action: HistoryRunAction,
    runId: string,
  ): Promise<void> {
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
          void onHistoryTableAction(
            action.action,
            action.runId ?? history.expandedRunId ?? "",
          );
          return;
        }
        toggleRunDetails(action.runId);
      },
    });
  }

  bindReactiveLanguageSync();

  return {
    bindHandlers,
    refreshHistory,
    deleteAllRuns,
    onHistoryTableAction,
    toggleRunDetails,
  };
}
