import { apiJson, apiJsonResponse } from "./http";
import { fromTransportPayload } from "../transport/http_adapters";
import type * as Local from "../transport/http_models";
import type * as Transport from "./types";

export function historyExportUrl(runId: string): string {
  return `/api/history/${encodeURIComponent(runId)}/export`;
}

export function historyReportPdfUrl(runId: string, lang: string): string {
  return `/api/history/${encodeURIComponent(runId)}/report.pdf?lang=${encodeURIComponent(lang)}`;
}

export async function getHistory(): Promise<Local.HistoryListPayload> {
  return fromTransportPayload<Transport.HistoryListPayload, Local.HistoryListPayload>(
    await apiJson<Transport.HistoryListPayload>("/api/history"),
  );
}

export async function deleteHistoryRun(runId: string): Promise<Local.DeleteHistoryRunPayload> {
  return fromTransportPayload<Transport.DeleteHistoryRunPayload, Local.DeleteHistoryRunPayload>(
    await apiJson<Transport.DeleteHistoryRunPayload>(`/api/history/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),
  );
}

export async function getHistoryRun(runId: string): Promise<Local.HistoryRunPayload> {
  return fromTransportPayload<Transport.HistoryRunPayload, Local.HistoryRunPayload>(
    await apiJson<Transport.HistoryRunPayload>(`/api/history/${encodeURIComponent(runId)}`),
  );
}

export async function getHistoryInsights(
  runId: string,
  lang: string,
): Promise<Local.HistoryInsightsResult> {
  const response = await apiJsonResponse<Transport.HistoryInsightsResult>(
    `/api/history/${encodeURIComponent(runId)}/insights?lang=${encodeURIComponent(lang)}`,
  );
  if (typeof response.body === "undefined") {
    throw new Error("Empty history insights response");
  }
  if (response.status === 202) {
    return fromTransportPayload<Transport.HistoryInsightsAnalyzingPayload, Local.HistoryInsightsAnalyzingPayload>(
      response.body as Transport.HistoryInsightsAnalyzingPayload,
    );
  }
  return fromTransportPayload<Transport.HistoryInsightsPayload, Local.HistoryInsightsPayload>(
    response.body as Transport.HistoryInsightsPayload,
  );
}
