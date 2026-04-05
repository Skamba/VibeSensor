import type { UiHistoryDom } from "../dom/history_dom";
import type { HistoryEntry } from "../../transport/http_models";
import type { RunDetail } from "../ui_app_state";
import {
  closestFromTarget,
  createInlineStatePanelElement,
  createTableEmptyRowElement,
  getTypedInlineStateAction,
} from "./dom_helpers";
import { renderChildren } from "./dom_render";
import { bindViewEvent, composeViewDisposers, type ViewDisposer } from "./dom_event_bindings";
import { buildHistoryTableRowsViewModel } from "./history_table_presenters";
import { createHistoryTableRowElements } from "./history_table_row_renderers";

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
const HISTORY_INLINE_ACTIONS = ["open-live"] as const;

export type HistoryRunAction = (typeof HISTORY_TABLE_ACTIONS)[number];

export interface HistoryTableAction {
  action: HistoryRunAction;
  runId: string | null;
}

export type HistoryTableInteraction =
  | { type: "open-live" }
  | { type: "run-action"; action: HistoryRunAction; runId: string | null }
  | { type: "toggle-run"; runId: string };

export interface HistoryTableBindingHandlers {
  onRefreshHistory(): void;
  onDeleteAllRuns(): void;
  onTableInteraction(action: HistoryTableInteraction): void;
}

export function renderHistoryEmptyState(
  container: HTMLElement,
  params: Pick<HistoryTableViewParams, "t">,
): void {
  const { t } = params;
  renderChildren(
    container,
    createTableEmptyRowElement(
      createInlineStatePanelElement({
        titleText: t("history.empty.title"),
        bodyText: t("history.empty.body"),
        detailText: t("history.empty.detail"),
        action: {
          action: "open-live",
          labelText: t("history.empty.action"),
        },
      }),
      4,
    ),
  );
}

export function renderHistoryTable(
  container: HTMLElement,
  params: HistoryTableViewParams,
): void {
  renderChildren(
    container,
    createHistoryTableRowElements(buildHistoryTableRowsViewModel(params), {
      historyExportUrl: params.historyExportUrl,
    }),
  );
}

export function getHistoryTableAction(
  target: EventTarget | null,
): HistoryTableAction | null {
  const actionElement = closestFromTarget<HTMLElement>(target, "[data-run-action]");
  if (!actionElement) {
    return null;
  }
  const action = HISTORY_TABLE_ACTIONS.find(
    (candidate) => candidate === actionElement.getAttribute("data-run-action"),
  );
  if (!action) {
    return null;
  }
  return {
    action,
    runId: actionElement.getAttribute("data-run"),
  };
}

export function getHistoryTableRowRunId(target: EventTarget | null): string | null {
  return closestFromTarget<HTMLElement>(target, 'tr[data-run-row="1"]')
    ?.getAttribute("data-run") ?? null;
}

export function bindHistoryTableInteractions(
  dom: Pick<UiHistoryDom, "refreshHistoryBtn" | "deleteAllRunsBtn" | "historyTableBody">,
  handlers: HistoryTableBindingHandlers,
): ViewDisposer {
  return composeViewDisposers(
    bindViewEvent(dom.refreshHistoryBtn, "click", () => {
      handlers.onRefreshHistory();
    }),
    bindViewEvent(dom.deleteAllRunsBtn, "click", () => {
      handlers.onDeleteAllRuns();
    }),
    bindViewEvent(dom.historyTableBody, "click", (event: MouseEvent) => {
      const inlineAction = getTypedInlineStateAction(event.target, HISTORY_INLINE_ACTIONS);
      if (inlineAction) {
        event.preventDefault();
        event.stopPropagation();
        handlers.onTableInteraction({ type: inlineAction });
        return;
      }
      const action = getHistoryTableAction(event.target);
      if (action) {
        if (action.action !== "download-raw") {
          event.preventDefault();
        }
        event.stopPropagation();
        handlers.onTableInteraction({
          type: "run-action",
          action: action.action,
          runId: action.runId,
        });
        return;
      }
      const runId = getHistoryTableRowRunId(event.target);
      if (runId) {
        handlers.onTableInteraction({ type: "toggle-run", runId });
      }
    }),
  );
}
