import { render } from "preact";
import { useUiText } from "../ui_i18n";
import {
  computed,
  signal,
  useComputed,
  type ReadonlySignal,
} from "../ui_signals";
import { HistoryTableBody } from "./history_table_content";
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

function HistoryPanel(props: {
  actions: ReadonlySignal<HistoryPanelActionHandlers | null>;
  model: ReadonlySignal<HistoryPanelRenderModel>;
}) {
  const refreshLabel = useUiText("history.refresh", "Refresh History");
  const deleteAllLabel = useUiText("history.delete_all", "Delete All Runs");
  const runLabel = useUiText("history.table.file", "Run");
  const startedLabel = useUiText("history.table.updated", "Started");
  const samplesLabel = useUiText("history.table.size", "Samples");
  const actionsLabel = useUiText("history.table.actions", "Actions");
  const deleteAllRunsDisabled = useComputed(() => props.model.value.deleteAllRunsDisabled);
  const historySummaryText = useComputed(() => props.model.value.historySummaryText);
  const table = useComputed(() => props.model.value.table);

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
            onClick={() => props.actions.value?.onRefreshHistory()}
          >
            {refreshLabel}
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"
            disabled={deleteAllRunsDisabled}
            onClick={() => props.actions.value?.onDeleteAllRuns()}
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
          <HistoryTableBody handlers={props.actions.value} table={table.value} />
        </tbody>
      </table>
    </>
  );
}

export function mountHistoryPanel(host: HTMLElement): HistoryPanelView {
  const actions = signal<HistoryPanelActionHandlers | null>(null);
  const modelSource = signal<ReadonlySignal<HistoryPanelRenderModel> | null>(null);
  const model = computed<HistoryPanelRenderModel>(() => modelSource.value?.value ?? DEFAULT_PANEL_MODEL);
  render(<HistoryPanel actions={actions} model={model} />, host);

  return {
    bindModel(model: ReadonlySignal<HistoryPanelRenderModel>): void {
      modelSource.value = model;
    },
    bindActions(handlers: HistoryPanelActionHandlers): void {
      actions.value = handlers;
    },
  };
}
