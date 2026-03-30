import type { FeatureDepsBase } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../ui_app_state";
import { getInlineStateAction } from "../views/dom_helpers";
import {
  getHistoryTableAction,
  getHistoryTableRowRunId,
} from "../views/history_table_view";
import {
  createHistoryDetailModule,
  type HistoryDetailModule,
} from "./history_detail_module";
import {
  createHistoryDownloadDeleteModule,
  type HistoryDownloadDeleteModule,
} from "./history_download_delete_module";
import {
  createHistoryListModule,
  type HistoryListModule,
} from "./history_list_module";

export interface HistoryFeatureDeps extends FeatureDepsBase {
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
  onHistoryTableAction(action: string, runId: string): Promise<void>;
  toggleRunDetails(runId: string): void;
  reloadExpandedRunOnLanguageChange(): void;
}

export function createHistoryFeature(ctx: HistoryFeatureDeps): HistoryFeature {
  const { history, els } = ctx;
  let handlersBound = false;
  let previewPrefetchToken = 0;

  function activatePrimaryView(viewId: string): void {
    els.menuButtons.find((button) => button.dataset.view === viewId)?.click();
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

  const listModule: HistoryListModule = createHistoryListModule({
    ...ctx,
    history,
    ensureRunDetail,
    collapseExpandedRun,
  });
  const detailModule: HistoryDetailModule = createHistoryDetailModule({
    ...ctx,
    history,
    ensureRunDetail,
    collapseExpandedRun,
    renderHistoryTable: () => listModule.renderHistoryTable(),
  });

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
        await detailModule.loadRunPreview(run.run_id);
      }
    })();
  }

  async function refreshHistory(): Promise<void> {
    await listModule.refreshHistory();
    prefetchCollapsedRunContext();
  }

  const downloadDeleteModule: HistoryDownloadDeleteModule = createHistoryDownloadDeleteModule({
    history,
    getLanguage: ctx.getLanguage,
    t: ctx.t,
    showError: ctx.showError,
    ensureRunDetail,
    collapseExpandedRun,
    renderHistoryTable: () => listModule.renderHistoryTable(),
    refreshHistory,
    loadRunInsights: (runId, force = false) => detailModule.loadRunInsights(runId, force),
  });

  function bindHandlers(): void {
    if (handlersBound) {
      return;
    }
    handlersBound = true;
    els.refreshHistoryBtn?.addEventListener("click", () => void refreshHistory());
    els.deleteAllRunsBtn?.addEventListener("click", () => void downloadDeleteModule.deleteAllRuns());
    els.historyTableBody?.addEventListener("click", (event) => {
      const inlineAction = getInlineStateAction(event.target);
      if (inlineAction === "open-live") {
        event.preventDefault();
        event.stopPropagation();
        activatePrimaryView("dashboardView");
        return;
      }
      const action = getHistoryTableAction(event.target);
      if (action) {
        if (action.action !== "download-raw") {
          event.preventDefault();
        }
        event.stopPropagation();
        void downloadDeleteModule.onHistoryTableAction(
          action.action,
          action.runId ?? history.expandedRunId ?? "",
        );
        return;
      }
      const runId = getHistoryTableRowRunId(event.target);
      if (runId) {
        detailModule.toggleRunDetails(runId);
      }
    });
  }

  return {
    bindHandlers,
    renderHistoryTable: () => listModule.renderHistoryTable(),
    refreshHistory,
    deleteAllRuns: () => downloadDeleteModule.deleteAllRuns(),
    onHistoryTableAction: (action, runId) => downloadDeleteModule.onHistoryTableAction(action, runId),
    toggleRunDetails: (runId) => detailModule.toggleRunDetails(runId),
    reloadExpandedRunOnLanguageChange: () => detailModule.reloadExpandedRunOnLanguageChange(),
  };
}
