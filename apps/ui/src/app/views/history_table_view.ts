import type { HistoryEntry } from "../../transport/http_models";
import type { RunDetail } from "../ui_app_state";

export interface HistoryTableViewParams {
  runs: HistoryEntry[];
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
  t: (key: string, vars?: Record<string, unknown>) => string;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  historyExportUrl: (runId: string) => string;
}

const HISTORY_TABLE_ACTIONS = [
  "download-pdf",
  "load-insights",
  "download-raw",
  "delete-run",
] as const;

export type HistoryRunAction = (typeof HISTORY_TABLE_ACTIONS)[number];

export type HistoryTableInteraction =
  | { type: "open-live" }
  | { type: "run-action"; action: HistoryRunAction; runId: string | null }
  | { type: "toggle-run"; runId: string };

export type HistoryPanelTableRenderModel =
  | {
      kind: "empty";
      t: (key: string, vars?: Record<string, unknown>) => string;
    }
  | {
      kind: "rows";
      params: HistoryTableViewParams;
    };

export interface HistoryPanelRenderModel {
  historySummaryText: string;
  deleteAllRunsDisabled: boolean;
  table: HistoryPanelTableRenderModel | null;
}

export interface HistoryPanelActionHandlers {
  onRefreshHistory(): void;
  onDeleteAllRuns(): void;
  onTableInteraction(action: HistoryTableInteraction): void;
}

export interface HistoryPanelView {
  render(model: HistoryPanelRenderModel): void;
  bindActions(handlers: HistoryPanelActionHandlers): void;
}
