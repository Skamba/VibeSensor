import { getHistoryInsights } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { AppState, RunDetail } from "../ui_app_state";

export interface HistoryDetailModuleDeps extends FeatureDepsBase {
  state: AppState;
  ensureRunDetail: (runId: string) => RunDetail;
  collapseExpandedRun: () => void;
  renderHistoryTable: () => void;
}

export interface HistoryDetailModule {
  loadRunPreview(runId: string, force?: boolean): Promise<void>;
  loadRunInsights(runId: string, force?: boolean): Promise<void>;
  toggleRunDetails(runId: string): void;
  reloadExpandedRunOnLanguageChange(): void;
}

export function createHistoryDetailModule(ctx: HistoryDetailModuleDeps): HistoryDetailModule {
  const { state, t } = ctx;

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ctx.ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) return;
    detail.previewLoading = true;
    detail.previewError = "";
    ctx.renderHistoryTable();
    try {
      detail.preview = await getHistoryInsights(runId, state.lang);
    } catch (err) {
      detail.previewError = err instanceof Error ? err.message : t("report.unable_load_insights");
    } finally {
      detail.previewLoading = false;
      ctx.renderHistoryTable();
    }
  }

  async function loadRunInsights(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ctx.ensureRunDetail(runId);
    if (!force && detail.insightsLoading) return;
    detail.insightsLoading = true;
    detail.insightsError = "";
    ctx.renderHistoryTable();
    try {
      detail.insights = await getHistoryInsights(runId, state.lang);
    } catch (err) {
      detail.insightsError = err instanceof Error ? err.message : t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      ctx.renderHistoryTable();
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) return;
    if (state.expandedRunId === runId) {
      ctx.collapseExpandedRun();
      ctx.renderHistoryTable();
      return;
    }
    ctx.collapseExpandedRun();
    state.expandedRunId = runId;
    ctx.renderHistoryTable();
    void loadRunPreview(runId);
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
    loadRunPreview,
    loadRunInsights,
    toggleRunDetails,
    reloadExpandedRunOnLanguageChange,
  };
}
