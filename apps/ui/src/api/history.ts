import { apiJson, apiJsonResponse } from "./http";
import type {
  DeleteHistoryRunPayload,
  HistoryInsightsAnalyzingPayload,
  HistoryInsightsPayload,
  HistoryInsightsResult,
  HistoryListPayload,
  HistoryRunPayload,
} from "./types";

export function historyExportUrl(runId: string): string {
  return `/api/history/${encodeURIComponent(runId)}/export`;
}

export function historyReportPdfUrl(runId: string, lang: string): string {
  return `/api/history/${encodeURIComponent(runId)}/report.pdf?lang=${encodeURIComponent(lang)}`;
}

export async function getHistory(): Promise<HistoryListPayload> {
  return apiJson("/api/history");
}

export async function deleteHistoryRun(runId: string): Promise<DeleteHistoryRunPayload> {
  return apiJson(`/api/history/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export async function getHistoryRun(runId: string): Promise<HistoryRunPayload> {
  return apiJson(`/api/history/${encodeURIComponent(runId)}`);
}

export async function getHistoryInsights(
  runId: string,
  lang: string,
): Promise<HistoryInsightsResult> {
  const response = await apiJsonResponse<HistoryInsightsResult>(
    `/api/history/${encodeURIComponent(runId)}/insights?lang=${encodeURIComponent(lang)}`,
  );
  if (typeof response.body === "undefined") {
    throw new Error("Empty history insights response");
  }
  if (response.status === 202) {
    return response.body as HistoryInsightsAnalyzingPayload;
  }
  return response.body as HistoryInsightsPayload;
}
