import { apiJson } from "./http";
import type { HistoryEntry } from "./types";

export function historyExportUrl(runId: string): string {
  return `/api/history/${encodeURIComponent(runId)}/export`;
}

export function historyReportPdfUrl(runId: string, lang: string): string {
  return `/api/history/${encodeURIComponent(runId)}/report.pdf?lang=${encodeURIComponent(lang)}`;
}

export async function getHistory(): Promise<{ runs: HistoryEntry[] }> {
  return apiJson("/api/history");
}

export async function deleteHistoryRun(runId: string): Promise<void> {
  await apiJson(`/api/history/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export async function getHistoryInsights(
  runId: string,
  lang: string,
  includeSamples = false,
): Promise<unknown> {
  return apiJson(
    `/api/history/${encodeURIComponent(runId)}/insights?lang=${encodeURIComponent(lang)}&include_samples=${includeSamples ? "1" : "0"}`,
  );
}
