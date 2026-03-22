import { getHistory, historyExportUrl } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { AppState, RunDetail } from "../ui_app_state";
import {
  renderHistoryEmptyState,
  renderHistoryTable as renderHistoryTableView,
} from "../views/history_table_view";

export interface HistoryListModuleDeps extends FeatureDepsBase {
  state: AppState;
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
  const { state, els, t, escapeHtml, fmt, fmtTs, formatInt } = ctx;

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
      ctx.collapseExpandedRun();
      return;
    }
    if (state.expandedRunId && !state.runs.some((row) => row.run_id === state.expandedRunId)) {
      ctx.collapseExpandedRun();
    }
    if (els.historySummary) {
      els.historySummary.textContent = t("history.available_count", { count: state.runs.length });
    }
    for (const run of state.runs) {
      ctx.ensureRunDetail(run.run_id);
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

  return {
    renderHistoryTable,
    refreshHistory,
  };
}
