import { render } from "preact";
import { useUiText } from "../ui_i18n";
import {
  signal,
  useComputed,
  useSignalProperties,
  type ReadonlySignal,
} from "../ui_signals";
import { HistoryTableBody } from "./history_table_content";
import { createDeferredViewModel, useDeferredViewModel } from "./view_model_binding";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
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

function HistoryPanel(props: {
  actions: ReadonlySignal<HistoryPanelActionHandlers | null>;
  model: ReadonlySignal<ReadonlySignal<HistoryPanelRenderModel> | null>;
}) {
  const refreshLabel = useUiText("history.refresh", "Refresh History");
  const deleteAllLabel = useUiText("history.delete_all", "Delete All Runs");
  const runLabel = useUiText("history.table.file", "Run");
  const startedLabel = useUiText("history.table.updated", "Started");
  const samplesLabel = useUiText("history.table.size", "Samples");
  const actionsLabel = useUiText("history.table.actions", "Actions");
  const actions = useComputed(() => props.actions.value);
  const model = useDeferredViewModel(props.model, DEFAULT_PANEL_MODEL);
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
          <HistoryTableBody handlers={actions.value} table={table} />
        </tbody>
      </table>
    </>
  );
}

export function mountHistoryPanel(host: HTMLElement): HistoryPanelView {
  const actions = signal<HistoryPanelActionHandlers | null>(null);
  const modelBinding = createDeferredViewModel<HistoryPanelRenderModel>();
  render(<HistoryPanel actions={actions} model={modelBinding.model} />, host);

  return {
    bindModel(model: ReadonlySignal<HistoryPanelRenderModel>): void {
      modelBinding.bind(model);
    },
    bindActions(handlers: HistoryPanelActionHandlers): void {
      actions.value = handlers;
    },
  };
}
