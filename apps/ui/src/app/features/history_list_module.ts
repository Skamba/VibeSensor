import { getHistory, historyExportUrl } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../ui_app_state";
import type {
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "../views/history_table_view";

export interface HistoryListModuleDeps extends FeatureDepsBase {
  panel: HistoryPanelView;
  history: HistoryState;
  fmt: (n: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  ensureRunDetail: (runId: string) => RunDetail;
  collapseExpandedRun: () => void;
}

export interface HistoryListModule {
  renderHistoryTable(): void;
  refreshHistory(): Promise<void>;
}

export function createHistoryListModule(ctx: HistoryListModuleDeps): HistoryListModule {
  const { history, panel, t, fmt, fmtTs, formatInt } = ctx;

  function renderModel(model: HistoryPanelRenderModel): void {
    panel.render(model);
  }

  function renderHistoryTable(): void {
    const deleteAllRunsDisabled = history.deleteAllRunsInFlight || history.runs.length === 0;
    if (!history.runs.length) {
      ctx.collapseExpandedRun();
      renderModel({
        historySummaryText: t("history.none"),
        deleteAllRunsDisabled,
        table: {
          kind: "empty",
          t,
        },
      });
      return;
    }
    if (history.expandedRunId && !history.runs.some((row) => row.run_id === history.expandedRunId)) {
      ctx.collapseExpandedRun();
    }
    for (const run of history.runs) {
      ctx.ensureRunDetail(run.run_id);
    }
    renderModel({
      historySummaryText: t("history.available_count", { count: history.runs.length }),
      deleteAllRunsDisabled,
      table: {
        kind: "rows",
        params: {
          runs: history.runs,
          expandedRunId: history.expandedRunId,
          runDetailsById: history.runDetailsById,
          t,
          fmt,
          fmtTs,
          formatInt,
          historyExportUrl,
        },
      },
    });
  }

  async function refreshHistory(): Promise<void> {
    try {
      const payload = await getHistory();
      history.runs = payload.runs ?? [];
      renderHistoryTable();
    } catch (_err) {
      renderHistoryTable();
    }
  }

  return {
    renderHistoryTable,
    refreshHistory,
  };
}
