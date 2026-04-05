import { getHistory, historyExportUrl } from "../../api";
import type { UiHistoryDom } from "../dom/history_dom";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../ui_app_state";
import {
  renderHistoryEmptyState,
  renderHistoryTable as renderHistoryTableView,
} from "../views/history_table_view";

export interface HistoryListModuleDeps extends FeatureDepsBase {
  dom: UiHistoryDom;
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
  const { history, dom: els, t, fmt, fmtTs, formatInt } = ctx;

  function renderHistoryTable(): void {
    if (els.deleteAllRunsBtn) {
      els.deleteAllRunsBtn.disabled = history.deleteAllRunsInFlight || history.runs.length === 0;
    }
    if (!history.runs.length) {
      if (els.historySummary) {
        els.historySummary.textContent = t("history.none");
      }
      if (els.historyTableBody) {
        renderHistoryEmptyState(els.historyTableBody, {
          t,
        });
      }
      ctx.collapseExpandedRun();
      return;
    }
    if (history.expandedRunId && !history.runs.some((row) => row.run_id === history.expandedRunId)) {
      ctx.collapseExpandedRun();
    }
    if (els.historySummary) {
      els.historySummary.textContent = t("history.available_count", { count: history.runs.length });
    }
    for (const run of history.runs) {
      ctx.ensureRunDetail(run.run_id);
    }
    if (els.historyTableBody) {
      renderHistoryTableView(els.historyTableBody, {
        runs: history.runs,
        expandedRunId: history.expandedRunId,
        runDetailsById: history.runDetailsById,
        t,
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
