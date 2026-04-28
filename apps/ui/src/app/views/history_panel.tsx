import { render } from "preact";
import { useUiText } from "../ui_i18n";
import {
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { HistoryTableBody } from "./history_table_content";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelView,
  HistoryPanelRenderModel,
} from "./history_table_view";
import { useDeferredModel } from "./view_model_binding";

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
  const actionsLabel = useUiText("history.table.actions", "Actions");
  const deleteAllLabel = useUiText("history.delete_all", "Delete All Runs");
  const refreshLabel = useUiText("history.refresh", "Refresh History");
  const runLabel = useUiText("history.table.file", "Run");
  const samplesLabel = useUiText("history.table.size", "Samples");
  const startedLabel = useUiText("history.table.updated", "Started");
  const model = useDeferredModel(props.model, DEFAULT_PANEL_MODEL);
  const { deleteAllRunsDisabled, historySummaryText, table } = useSignalProperties(
    model,
    HISTORY_PANEL_MODEL_KEYS,
  );
  const handleRefreshHistory = () => {
    props.actions.peek()?.onRefreshHistory();
  };
  const handleDeleteAllRuns = () => {
    props.actions.peek()?.onDeleteAllRuns();
  };
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
            {refreshLabel}
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"
            disabled={deleteAllRunsDisabled}
            onClick={handleDeleteAllRuns}
          >
            {deleteAllLabel}
          </button>
        </div>
      </div>
      <table class="history-table">
        <thead>
          <tr>
            <th>{runLabel}</th>
            <th>{startedLabel}</th>
            <th class="numeric">{samplesLabel}</th>
            <th>{actionsLabel}</th>
          </tr>
        </thead>
        <tbody id="historyTableBody">
          <HistoryTableBody handlers={props.actions.value} table={table} />
        </tbody>
      </table>
    </>
  );
}

function mountHistoryPanel(host: HTMLElement, view: HistoryPanelView): void {
  render(<HistoryPanel actions={view.actions} model={view.model} />, host);
}
