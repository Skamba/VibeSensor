import { apiJson } from "./http";
import type {
  DeleteHistoryRunPayload,
  HistoryInsightsPayload,
  HistoryListPayload,
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

export async function getHistoryInsights(
  runId: string,
  lang: string,
): Promise<HistoryInsightsPayload> {
  return apiJson(
    `/api/history/${encodeURIComponent(runId)}/insights?lang=${encodeURIComponent(lang)}`,
  );
}
