import type { JSX } from "preact";

import { useComputed, useSignal, type ReadonlySignal } from "../ui_signals";
import { inlineStateActionClass } from "./dom_helpers";
import { HistoryDetailsRow } from "./history_detail_expansion";
import { HistorySummaryChips } from "./history_summary_chips";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelTableRenderModel,
  HistoryRunAction,
} from "./history_table_view";
import type {
  HistoryDetailsViewModel,
  HistoryRowViewModel,
} from "./history_table_models";
import { createHistoryTableRowsMemo } from "./history_table_presenters";

function stopRowToggle(event: JSX.TargetedMouseEvent<HTMLElement>): void {
  event.stopPropagation();
}

function handleRunAction(
  event: JSX.TargetedMouseEvent<HTMLElement>,
  handlers: HistoryPanelActionHandlers | null,
  action: HistoryRunAction,
  runId: string,
): void {
  event.preventDefault();
  event.stopPropagation();
  handlers?.onTableInteraction({
    type: "run-action",
    action,
    runId,
  });
}

function useHistoryTableRows(
  table: ReadonlySignal<HistoryPanelTableRenderModel | null>,
): ReadonlySignal<HistoryRowViewModel[] | null> {
  const rowsMemo = useSignal(createHistoryTableRowsMemo());

  return useComputed(() => {
    const nextTable = table.value;
    if (nextTable === null || nextTable.kind !== "rows") {
      return null;
    }
    return rowsMemo.value(nextTable.params);
  });
}

function HistoryEmptyStateRow(props: {
  handlers: HistoryPanelActionHandlers | null;
  t: (key: string, vars?: Record<string, unknown>) => string;
}) {
  const { handlers, t } = props;
  return (
    <tr>
      <td colSpan={4}>
        <div class="empty-state empty-state--inline empty-state--actionable">
          <strong class="empty-state__title">{t("history.empty.title")}</strong>
          <span class="empty-state__body">{t("history.empty.body")}</span>
          <span class="empty-state__detail">{t("history.empty.detail")}</span>
          <div class="empty-state__actions">
            <button
              type="button"
              class={inlineStateActionClass(undefined)}
              data-inline-state-action="open-live"
              onClick={() => handlers?.onTableInteraction({ type: "open-live" })}
            >
              {t("history.empty.action")}
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}

function HistoryDiagnosisSummary(props: { row: HistoryRowViewModel }) {
  const { row } = props;
  if (!row.summaryHeadline && !row.summaryMeta) {
    return null;
  }
  return (
    <div class="history-row__diagnosis">
      {row.summaryHeadline ? (
        <div class="history-row__diagnosis-title">{row.summaryHeadline}</div>
      ) : null}
      {row.summaryMeta ? (
        <div class="history-row__diagnosis-meta">{row.summaryMeta}</div>
      ) : null}
    </div>
  );
}

function HistoryCollapsedRowActions(props: {
  handlers: HistoryPanelActionHandlers | null;
  row: HistoryRowViewModel;
}) {
  const { handlers, row } = props;
  if (row.collapsedAction.hintText) {
    return <div class="history-row__action-hint">{row.collapsedAction.hintText}</div>;
  }
  return (
    <div class="table-actions history-row__actions">
      <button
        class="btn btn--muted"
        type="button"
        disabled={row.collapsedAction.pdfLoading}
        data-run-action="download-pdf"
        data-run={row.runId}
        onClick={(event) => handleRunAction(event, handlers, "download-pdf", row.runId)}
      >
        {row.collapsedAction.pdfLabel ?? ""}
      </button>
    </div>
  );
}

function HistoryRow(props: {
  handlers: HistoryPanelActionHandlers | null;
  row: HistoryRowViewModel;
}) {
  const { handlers, row } = props;
  return (
    <tr
      class={`history-row${row.isExpanded ? " history-row--expanded" : ""}`}
      data-run-row="1"
      data-run={row.runId}
      onClick={() => handlers?.onTableInteraction({ type: "toggle-run", runId: row.runId })}
    >
      <td class="history-row__primary-cell">
        <div class="history-row__run">
          <div class="history-row__run-heading">
            <div class="history-row__car-context">
              <span class="history-row__car-label">{row.carLabel}</span>
              <span class="history-row__car-name">{row.carName}</span>
            </div>
            <div class="history-row__run-id">{row.runId}</div>
          </div>
          <HistorySummaryChips row={row} />
          <div class="history-row__detail-affordance">
            <HistoryDiagnosisSummary row={row} />
            <button
              class={`history-row__toggle${row.isExpanded ? " history-row__toggle--expanded" : ""}`}
              type="button"
              aria-expanded={row.isExpanded ? "true" : "false"}
              aria-label={row.toggleTitle}
              title={row.toggleTitle}
              data-run-toggle="details"
              data-run={row.runId}
              onClick={(event) => {
                event.stopPropagation();
                handlers?.onTableInteraction({ type: "toggle-run", runId: row.runId });
              }}
            >
              <span class="history-row__toggle-icon" aria-hidden="true" />
              <span class="history-row__toggle-copy">
                <span class="history-row__toggle-title">{row.toggleLabel}</span>
              </span>
            </button>
          </div>
        </div>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--started">
        <span class="history-row__meta-label">{row.startedLabel}</span>
        <span class="history-row__meta-value">{row.startedAtText}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--samples numeric">
        <span class="history-row__meta-label">{row.sizeLabel}</span>
        <span class="history-row__meta-value">{row.sampleCountText}</span>
      </td>
      <td class="history-row__meta-cell history-row__meta-cell--actions">
        <span class="history-row__meta-label">{row.quickReportLabel}</span>
        <HistoryCollapsedRowActions handlers={handlers} row={row} />
        {row.pdfError ? <div class="history-inline-error">{row.pdfError}</div> : null}
      </td>
    </tr>
  );
}

export function HistoryTableBody(props: {
  handlers: HistoryPanelActionHandlers | null;
  table: ReadonlySignal<HistoryPanelTableRenderModel | null>;
}) {
  const { handlers } = props;
  const tableKind = useComputed(() => props.table.value?.kind ?? null);
  const emptyStateTranslate = useComputed(() =>
    props.table.value?.kind === "empty" ? props.table.value.t : null
  );
  const historyExportUrl = useComputed(() =>
    props.table.value?.kind === "rows" ? props.table.value.params.historyExportUrl : null
  );
  const rows = useHistoryTableRows(props.table);

  if (tableKind.value === null) {
    return (
      <tr>
        <td colSpan={4}>No runs found.</td>
      </tr>
    );
  }
  if (tableKind.value === "empty") {
    const translate = emptyStateTranslate.value;
    if (translate === null) {
      throw new Error("History empty-state translation missing");
    }
    return <HistoryEmptyStateRow handlers={handlers} t={translate} />;
  }

  const currentRows = rows.value;
  const currentHistoryExportUrl = historyExportUrl.value;
  if (currentRows === null || currentHistoryExportUrl === null) {
    throw new Error("History row params missing");
  }
  return (
    <>
      {currentRows.flatMap((row) => [
        <HistoryRow key={`row:${row.runId}`} handlers={handlers} row={row} />,
        row.details ? (
          <HistoryDetailsRow
            key={`details:${row.runId}`}
            details={row.details}
            historyExportUrl={currentHistoryExportUrl}
            onRunAction={(event, action, runId) => handleRunAction(event, handlers, action, runId)}
            onStopRowToggle={stopRowToggle}
            row={row}
          />
        ) : null,
      ])}
    </>
  );
}
