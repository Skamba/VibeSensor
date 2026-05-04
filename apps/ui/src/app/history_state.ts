import type { HistoryEntry, HistoryInsightsPayload } from "../api/types";
import { signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface RunDetail {
  preview: HistoryInsightsPayload | null;
  previewLoading: boolean;
  previewError: string;
  insights: HistoryInsightsPayload | null;
  insightsLoading: boolean;
  insightsError: string;
  pdfLoading: boolean;
  pdfError: string;
}

export interface HistoryStateValue {
  runs: HistoryEntry[];
  deleteAllRunsInFlight: boolean;
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
}

export type HistoryState = SignalState<HistoryStateValue>;

export function createHistoryState(): HistoryState {
  return {
    runs: signal<HistoryEntry[]>([]),
    deleteAllRunsInFlight: signal(false),
    expandedRunId: signal<string | null>(null),
    runDetailsById: signal<Record<string, RunDetail>>({}),
  };
}
