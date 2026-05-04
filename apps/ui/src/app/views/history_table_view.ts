import type { HistoryEntry } from "../../api/types";
import type { RunDetail } from "../history_state";
import type { Signal } from "../ui_signals";
import type { HistoryRowViewModel } from "./history_table_models";
import type { DeferredModelSignal } from "./view_model_binding";

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
      historyExportUrl: (runId: string) => string;
      rows: HistoryRowViewModel[];
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
  actions: Signal<HistoryPanelActionHandlers | null>;
  model: DeferredModelSignal<HistoryPanelRenderModel>;
}
