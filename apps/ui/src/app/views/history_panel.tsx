import { render } from "preact";
import { getUiText } from "../ui_i18n";
import {
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { HistoryTableBody } from "./history_table_content";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelView,
  HistoryPanelRenderModel,
} from "./history_table_view";

const DEFAULT_PANEL_MODEL: HistoryPanelRenderModel = {
  deleteAllRunsDisabled: true,
  historySummaryText: "No runs yet.",
  table: null,
};

const HISTORY_PANEL_MODEL_KEYS = [
  "deleteAllRunsDisabled",
  "historySummaryText",
  "table",
] as const;

export function HistoryPanel(props: {
  actions: ReadonlySignal<HistoryPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<HistoryPanelRenderModel> | null>;
}) {
  const actions = useComputed(() => props.actions.value);
  const labels = useComputed(() => ({
    actionsLabel: getUiText("history.table.actions", "Actions"),
    deleteAllLabel: getUiText("history.delete_all", "Delete All Runs"),
    refreshLabel: getUiText("history.refresh", "Refresh History"),
    runLabel: getUiText("history.table.file", "Run"),
    samplesLabel: getUiText("history.table.size", "Samples"),
    startedLabel: getUiText("history.table.updated", "Started"),
  }));
  const model = useComputed(() => props.model.value?.value ?? DEFAULT_PANEL_MODEL);
  const { deleteAllRunsDisabled, historySummaryText, table } = useSignalProperties(
    model,
    HISTORY_PANEL_MODEL_KEYS,
  );
  const handleRefreshHistory = () => {
    actions.value?.onRefreshHistory();
  };
  const handleDeleteAllRuns = () => {
    actions.value?.onDeleteAllRuns();
  };
  const labelTexts = labels.value;

  return (
    <>
      <div class="history-toolbar">
        <div class="history-toolbar__copy">
          <div id="historySummary" class="history-toolbar__summary subtle">
            {historySummaryText}
          </div>
        </div>
        <div class="history-toolbar__actions">
          <button
            id="refreshHistoryBtn"
            class="btn btn--muted"
            type="button"
            onClick={handleRefreshHistory}
          >
            {labelTexts.refreshLabel}
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"
            disabled={deleteAllRunsDisabled}
            onClick={handleDeleteAllRuns}
          >
            {labelTexts.deleteAllLabel}
          </button>
        </div>
      </div>
      <table class="history-table">
        <thead>
          <tr>
            <th>{labelTexts.runLabel}</th>
            <th>{labelTexts.startedLabel}</th>
            <th class="numeric">{labelTexts.samplesLabel}</th>
            <th>{labelTexts.actionsLabel}</th>
          </tr>
        </thead>
        <tbody id="historyTableBody">
          <HistoryTableBody handlers={actions.value} table={table} />
        </tbody>
      </table>
    </>
  );
}

export function mountHistoryPanel(host: HTMLElement, view: HistoryPanelView): void {
  render(<HistoryPanel actions={view.actions} model={view.model} />, host);
}
