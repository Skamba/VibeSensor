import type { QueryClient } from "@tanstack/query-core";

import {
  deleteHistoryRun as deleteHistoryRunApi,
  getHistory,
  getHistoryInsights,
  historyExportUrl,
  historyReportPdfUrl,
} from "../../api";
import type { FeatureFormatting, FeatureServices } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../history_state";
import type { ShellState } from "../shell_state";
import { computed, effectOnChange, untracked } from "../ui_signals";
import type {
  HistoryPanelRenderModel,
  HistoryPanelView,
  HistoryRunAction,
} from "../views/history_table_view";
import {
  buildHistoryRowsTableRenderModel,
  createHistoryTableRowsMemo,
} from "../views/history_table_presenters";
import { historyPostAnalysisReady } from "../views/history_presenter_shared";
import { downloadBlobFile } from "./history_download";
import { serverStateQueryKeys } from "./server_state_query_keys";

export interface HistoryFeatureDeps {
  panel: HistoryPanelView;
  navigation: {
    activatePrimaryView(viewId: string): void;
  };
  queryClient: QueryClient;
  history: HistoryState;
  shell: Pick<ShellState, "lang">;
  services: FeatureServices;
  formatting: FeatureFormatting;
}

export interface HistoryFeature {
  bindHandlers(): void;
  dispose(): void;
  refreshHistory(): Promise<void>;
  deleteAllRuns(): Promise<void>;
  onHistoryTableAction(action: HistoryRunAction, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { history, panel, shell, services, formatting } = ctx;
  const COLLAPSED_RUN_PREVIEW_PREFETCH_CONCURRENCY = 3;
  let handlersBound = false;
  let previewPrefetchToken = 0;
  const rowsMemo = createHistoryTableRowsMemo();

  function activatePrimaryView(viewId: string): void {
    ctx.navigation.activatePrimaryView(viewId);
  }

  function ensureRunDetail(runId: string): RunDetail {
    const existing = history.runDetailsById.value[runId];
    if (existing) {
      return existing;
    }
    const nextDetail: RunDetail = {
      preview: null,
      previewLoading: false,
      previewError: "",
      insights: null,
      insightsLoading: false,
      insightsError: "",
      pdfLoading: false,
      pdfError: "",
    };
    history.runDetailsById.value = {
      ...history.runDetailsById.value,
      [runId]: nextDetail,
    };
    return nextDetail;
  }

  function updateRunDetail(
    runId: string,
    updater: (detail: RunDetail) => RunDetail,
  ): RunDetail {
    const nextDetail = updater(ensureRunDetail(runId));
    history.runDetailsById.value = {
      ...history.runDetailsById.value,
      [runId]: nextDetail,
    };
    return nextDetail;
  }

  function removeRunDetail(runId: string): void {
    const { [runId]: _removed, ...rest } = history.runDetailsById.value;
    history.runDetailsById.value = rest;
  }

  function collapseExpandedRun(): void {
    const previous = history.expandedRunId.value;
    history.expandedRunId.value = null;
    if (previous) {
      removeRunDetail(previous);
    }
  }

  function buildPanelRenderModel(): HistoryPanelRenderModel {
    const runs = history.runs.value;
    const deleteAllRunsDisabled =
      history.deleteAllRunsInFlight.value || runs.length === 0;
    const expandedRunId =
      history.expandedRunId.value &&
      runs.some((row) => row.run_id === history.expandedRunId.value)
        ? history.expandedRunId.value
        : null;
    if (!runs.length) {
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
        count: runs.length,
      }),
      deleteAllRunsDisabled,
      table: (() => {
        const params = {
          runs,
          expandedRunId,
          runDetailsById: history.runDetailsById.value,
          t: services.t,
          fmt: formatting.fmt,
          fmtTs: formatting.fmtTs,
          formatInt: formatting.formatInt,
          historyExportUrl,
        };
        return buildHistoryRowsTableRenderModel(params, rowsMemo(params));
      })(),
    };
  }

  const panelModel = computed(buildPanelRenderModel);
  panel.model.value = panelModel;

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) {
      return;
    }
    const detail = ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) {
      return;
    }
    updateRunDetail(runId, (current) => ({
      ...current,
      previewLoading: true,
      previewError: "",
    }));
    try {
      const response = await ctx.queryClient.fetchQuery({
        queryFn: () => getHistoryInsights(runId, shell.lang.value),
        queryKey: serverStateQueryKeys.history.insights(
          runId,
          shell.lang.value,
        ),
        staleTime: 0,
      });
      updateRunDetail(runId, (current) => ({
        ...current,
        preview: response.status === "complete" ? response : null,
      }));
    } catch (err) {
      updateRunDetail(runId, (current) => ({
        ...current,
        previewError:
          err instanceof Error
            ? err.message
            : services.t("report.unable_load_insights"),
      }));
    } finally {
      updateRunDetail(runId, (current) => ({
        ...current,
        previewLoading: false,
      }));
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
    updateRunDetail(runId, (current) => ({
      ...current,
      insightsLoading: true,
      insightsError: "",
    }));
    try {
      const response = await ctx.queryClient.fetchQuery({
        queryFn: () => getHistoryInsights(runId, shell.lang.value),
        queryKey: serverStateQueryKeys.history.insights(
          runId,
          shell.lang.value,
        ),
        staleTime: 0,
      });
      updateRunDetail(runId, (current) => ({
        ...current,
        insights: response.status === "complete" ? response : null,
      }));
    } catch (err) {
      updateRunDetail(runId, (current) => ({
        ...current,
        insightsError:
          err instanceof Error
            ? err.message
            : services.t("report.unable_load_insights"),
      }));
    } finally {
      updateRunDetail(runId, (current) => ({
        ...current,
        insightsLoading: false,
      }));
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) {
      return;
    }
    if (history.expandedRunId.value === runId) {
      collapseExpandedRun();
      return;
    }
    collapseExpandedRun();
    history.expandedRunId.value = runId;
    void loadRunPreview(runId);
  }

  function reloadExpandedRunOnLanguageChange(): void {
    if (!history.expandedRunId.value) {
      return;
    }
    const runId = history.expandedRunId.value;
    const detail = history.runDetailsById.value[runId];
    const shouldReloadInsights = Boolean(detail?.insights);
    removeRunDetail(runId);
    void loadRunPreview(runId, true).then(() => {
      if (shouldReloadInsights) {
        void loadRunInsights(runId, true);
      }
    });
  }

  function bindReactiveLanguageSync(): () => void {
    return effectOnChange(shell.lang, () => {
      untracked(() => {
        reloadExpandedRunOnLanguageChange();
      });
    });
  }

  function prefetchCollapsedRunContext(): void {
    const token = ++previewPrefetchToken;
    void (async () => {
      const readyRuns = history.runs.value.filter((run) =>
        historyPostAnalysisReady(run),
      );
      for (
        let index = 0;
        index < readyRuns.length;
        index += COLLAPSED_RUN_PREVIEW_PREFETCH_CONCURRENCY
      ) {
        if (token !== previewPrefetchToken) {
          return;
        }
        const batch = readyRuns.slice(
          index,
          index + COLLAPSED_RUN_PREVIEW_PREFETCH_CONCURRENCY,
        );
        await Promise.all(batch.map((run) => loadRunPreview(run.run_id)));
      }
    })();
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await ctx.queryClient.fetchQuery({
        queryFn: () => getHistory(),
        queryKey: serverStateQueryKeys.history.runs(),
        staleTime: 0,
      });
      history.runs.value = payload.runs ?? [];
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
        err instanceof Error
          ? err.message
          : services.t("history.delete_failed"),
      );
      return;
    }
    if (history.expandedRunId.value === runId) {
      collapseExpandedRun();
    }
    await ctx.queryClient.invalidateQueries({
      queryKey: serverStateQueryKeys.history.runs(),
    });
    await refreshHistory();
  }

  async function deleteAllRuns(): Promise<void> {
    const names = history.runs.value.map((row) => row.run_id).filter(Boolean);
    if (!names.length) {
      return;
    }
    const ok = await services.requestConfirmation(
      services.t("history.delete_all_confirm", { count: names.length }),
    );
    if (!ok) {
      return;
    }

    history.deleteAllRunsInFlight.value = true;
    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const name of names) {
      try {
        await deleteHistoryRunApi(name);
        deleted += 1;
        removeRunDetail(name);
        if (history.expandedRunId.value === name) {
          collapseExpandedRun();
        }
      } catch (err) {
        failed += 1;
        if (!firstError) {
          firstError =
            err instanceof Error
              ? err.message
              : services.t("history.delete_failed");
        }
      }
    }
    history.deleteAllRunsInFlight.value = false;
    await ctx.queryClient.invalidateQueries({
      queryKey: serverStateQueryKeys.history.runs(),
    });
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
    updateRunDetail(runId, (current) => ({
      ...current,
      pdfLoading: true,
      pdfError: "",
    }));
    try {
      await downloadBlobFile(
        historyReportPdfUrl(runId, shell.lang.value),
        `${runId}_report.pdf`,
      );
    } catch (err) {
      updateRunDetail(runId, (current) => ({
        ...current,
        pdfError:
          err instanceof Error ? err.message : services.t("history.pdf_failed"),
      }));
    } finally {
      updateRunDetail(runId, (current) => ({
        ...current,
        pdfLoading: false,
      }));
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
    panel.actions.value = {
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
            action.runId ?? history.expandedRunId.value ?? "",
          );
          return;
        }
        toggleRunDetails(action.runId);
      },
    };
  }

  const disposeLanguageSync = bindReactiveLanguageSync();

  return {
    bindHandlers,
    dispose(): void {
      previewPrefetchToken += 1;
      disposeLanguageSync();
    },
    refreshHistory,
    deleteAllRuns,
    onHistoryTableAction,
    toggleRunDetails,
  };
}
