import { getHistoryInsights } from "../../api";
import type { FeatureDepsBase } from "../feature_deps_base";
import type { HistoryState, RunDetail } from "../ui_app_state";

export interface HistoryDetailModuleDeps extends FeatureDepsBase {
  history: HistoryState;
  getLanguage: () => string;
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
  const { history, t } = ctx;

  async function loadRunPreview(runId: string, force = false): Promise<void> {
    if (!runId) return;
    const detail = ctx.ensureRunDetail(runId);
    if (!force && (detail.previewLoading || detail.preview)) return;
    detail.previewLoading = true;
    detail.previewError = "";
    ctx.renderHistoryTable();
    try {
      const response = await getHistoryInsights(runId, ctx.getLanguage());
      detail.preview = response.status === "complete" ? response : null;
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
      const response = await getHistoryInsights(runId, ctx.getLanguage());
      detail.insights = response.status === "complete" ? response : null;
    } catch (err) {
      detail.insightsError = err instanceof Error ? err.message : t("report.unable_load_insights");
    } finally {
      detail.insightsLoading = false;
      ctx.renderHistoryTable();
    }
  }

  function toggleRunDetails(runId: string): void {
    if (!runId) return;
    if (history.expandedRunId === runId) {
      ctx.collapseExpandedRun();
      ctx.renderHistoryTable();
      return;
    }
    ctx.collapseExpandedRun();
    history.expandedRunId = runId;
    ctx.renderHistoryTable();
    void loadRunPreview(runId);
  }

  function reloadExpandedRunOnLanguageChange(): void {
    if (!history.expandedRunId) return;
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

  return {
    loadRunPreview,
    loadRunInsights,
    toggleRunDetails,
    reloadExpandedRunOnLanguageChange,
  };
}
