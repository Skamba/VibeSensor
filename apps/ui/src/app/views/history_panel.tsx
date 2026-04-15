import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { HistoryTableBody } from "./history_table_content";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "./history_table_view";

interface HistoryPanelBridgeState extends HistoryPanelRenderModel {
  actions: HistoryPanelActionHandlers | null;
}

const DEFAULT_PANEL_STATE: HistoryPanelBridgeState = {
  historySummaryText: "No runs yet.",
  deleteAllRunsDisabled: true,
  table: null,
  actions: null,
};

function HistoryPanel(props: { state: HistoryPanelBridgeState }) {
  const { state } = props;

  return (
    <>
      <div class="history-toolbar">
        <div class="history-toolbar__copy">
          <div id="historySummary" class="history-toolbar__summary subtle">
            {state.historySummaryText}
          </div>
        </div>
        <div class="history-toolbar__actions">
          <button
            id="refreshHistoryBtn"
            class="btn btn--muted"
            type="button"
            data-i18n="history.refresh"
            onClick={() => state.actions?.onRefreshHistory()}
          >
            Refresh History
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"
            data-i18n="history.delete_all"
            disabled={state.deleteAllRunsDisabled}
            onClick={() => state.actions?.onDeleteAllRuns()}
          >
            Delete All Runs
          </button>
        </div>
      </div>
      <table class="history-table">
        <thead>
          <tr>
            <th data-i18n="history.table.file">Run</th>
            <th data-i18n="history.table.updated">Started</th>
            <th class="numeric" data-i18n="history.table.size">Samples</th>
            <th data-i18n="history.table.actions">Actions</th>
          </tr>
        </thead>
        <tbody id="historyTableBody">
          <HistoryTableBody handlers={state.actions} table={state.table} />
        </tbody>
      </table>
    </>
  );
}

export function mountHistoryPanel(host: HTMLElement): HistoryPanelView {
  const mount = createUiPreactMount(host);
  let state: HistoryPanelBridgeState = { ...DEFAULT_PANEL_STATE };

  function render(): void {
    mount.render(<HistoryPanel state={state} />);
  }

  render();

  return {
    render(model: HistoryPanelRenderModel): void {
      state = { ...state, ...model };
      render();
    },
    bindActions(handlers: HistoryPanelActionHandlers): void {
      state = { ...state, actions: handlers };
      render();
    },
  };
}
