import type { HistoryEntry } from "../../api/types";
import type { RunDetail } from "../ui_app_state";
import {
  closestFromTarget,
  renderInlineStatePanel,
  renderTableEmptyRow,
} from "./dom_helpers";
import { buildHistoryTableRowsViewModel } from "./history_table_presenters";
import { renderHistoryTableRows } from "./history_table_row_renderers";

export interface HistoryTableViewParams {
  runs: HistoryEntry[];
  expandedRunId: string | null;
  runDetailsById: Record<string, RunDetail>;
  t: (key: string, vars?: Record<string, unknown>) => string;
  escapeHtml: (value: unknown) => string;
  fmt: (value: number, digits?: number) => string;
  fmtTs: (iso: string) => string;
  formatInt: (value: number) => string;
  historyExportUrl: (runId: string) => string;
}

export interface HistoryTableAction {
  action: string;
  runId: string | null;
}

export function renderHistoryEmptyState(
  container: HTMLElement,
  params: Pick<HistoryTableViewParams, "escapeHtml" | "t">,
): void {
  const { escapeHtml, t } = params;
  container.innerHTML = renderTableEmptyRow(
    renderInlineStatePanel({
      titleHtml: escapeHtml(t("history.empty.title")),
      bodyHtml: escapeHtml(t("history.empty.body")),
      detailHtml: escapeHtml(t("history.empty.detail")),
      action: {
        action: "open-live",
        labelHtml: escapeHtml(t("history.empty.action")),
      },
    }),
    4,
  );
}

export function renderHistoryTable(
  container: HTMLElement,
  params: HistoryTableViewParams,
): void {
  container.innerHTML = renderHistoryTableRows(
    buildHistoryTableRowsViewModel(params),
    {
      escapeHtml: params.escapeHtml,
      historyExportUrl: params.historyExportUrl,
    },
  );
}

export function getHistoryTableAction(
  target: EventTarget | null,
): HistoryTableAction | null {
  const actionElement = closestFromTarget<HTMLElement>(target, "[data-run-action]");
  if (!actionElement) {
    return null;
  }
  return {
    action: actionElement.getAttribute("data-run-action") ?? "",
    runId: actionElement.getAttribute("data-run"),
  };
}

export function getHistoryTableRowRunId(target: EventTarget | null): string | null {
  return closestFromTarget<HTMLElement>(target, 'tr[data-run-row="1"]')
    ?.getAttribute("data-run") ?? null;
}
