import { deleteHistoryRun as deleteHistoryRunApi, historyReportPdfUrl } from "../../api";
import type { AppState, RunDetail } from "../ui_app_state";

const DOWNLOAD_REVOKE_DELAY_MS = 1000;

export function filenameFromDisposition(headerValue: string | null, fallback: string): string {
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

export async function downloadBlobFile(url: string, fallbackName: string): Promise<void> {
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

export interface HistoryDownloadDeleteModuleDeps {
  state: AppState;
  t: (key: string, vars?: Record<string, unknown>) => string;
  ensureRunDetail: (runId: string) => RunDetail;
  collapseExpandedRun: () => void;
  renderHistoryTable: () => void;
  refreshHistory: () => Promise<void>;
  loadRunInsights: (runId: string, force?: boolean) => Promise<void>;
}

export interface HistoryDownloadDeleteModule {
  deleteRun(runId: string): Promise<void>;
  deleteAllRuns(): Promise<void>;
  downloadReportPdfForRun(runId: string): Promise<void>;
  onHistoryTableAction(action: string, runId: string): Promise<void>;
}

export function createHistoryDownloadDeleteModule(
  ctx: HistoryDownloadDeleteModuleDeps,
): HistoryDownloadDeleteModule {
  const { state, t } = ctx;

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
      ctx.collapseExpandedRun();
    }
    await ctx.refreshHistory();
  }

  async function deleteAllRuns(): Promise<void> {
    const names = state.runs.map((row) => row.run_id).filter(Boolean);
    if (!names.length) return;
    const ok = window.confirm(t("history.delete_all_confirm", { count: names.length }));
    if (!ok) return;

    state.deleteAllRunsInFlight = true;
    ctx.renderHistoryTable();
    let deleted = 0;
    let failed = 0;
    let firstError = "";
    for (const name of names) {
      try {
        await deleteHistoryRunApi(name);
        deleted += 1;
        delete state.runDetailsById[name];
        if (state.expandedRunId === name) {
          ctx.collapseExpandedRun();
        }
      } catch (err) {
        failed += 1;
        if (!firstError) {
          firstError = err instanceof Error ? err.message : t("history.delete_failed");
        }
      }
    }
    state.deleteAllRunsInFlight = false;
    await ctx.refreshHistory();
    if (failed > 0) {
      const summary = t("history.delete_all_partial", { deleted, total: names.length, failed });
      window.alert(firstError ? `${summary}\n${firstError}` : summary);
    }
  }

  async function downloadReportPdfForRun(runId: string): Promise<void> {
    const detail = ctx.ensureRunDetail(runId);
    if (detail.pdfLoading) return;
    detail.pdfLoading = true;
    detail.pdfError = "";
    ctx.renderHistoryTable();
    try {
      await downloadBlobFile(historyReportPdfUrl(runId, state.lang), `${runId}_report.pdf`);
    } catch (err) {
      detail.pdfError = err instanceof Error ? err.message : t("history.pdf_failed");
    } finally {
      detail.pdfLoading = false;
      ctx.renderHistoryTable();
    }
  }

  async function onHistoryTableAction(action: string, runId: string): Promise<void> {
    if (!action || !runId) return;
    if (action === "download-pdf") return downloadReportPdfForRun(runId);
    if (action === "delete-run") return deleteRun(runId);
    if (action === "load-insights") {
      await ctx.loadRunInsights(runId, true);
    }
  }

  return {
    deleteRun,
    deleteAllRuns,
    downloadReportPdfForRun,
    onHistoryTableAction,
  };
}
