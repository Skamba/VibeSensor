import { render } from "preact";
import { useUiTranslation } from "../ui_i18n";
import { signal, type ReadonlySignal } from "../ui_signals";
import { HistoryTableBody } from "./history_table_content";
import type {
  HistoryPanelActionHandlers,
  HistoryPanelRenderModel,
  HistoryPanelView,
} from "./history_table_view";

interface HistoryPanelBridgeState {
  actions: HistoryPanelActionHandlers | null;
  model: ReadonlySignal<HistoryPanelRenderModel> | null;
}

const DEFAULT_PANEL_STATE: HistoryPanelBridgeState = {
  actions: null,
  model: null,
};

function HistoryPanel(props: { state: ReadonlySignal<HistoryPanelBridgeState> }) {
  const state = props.state.value;
  const model = state.model?.value ?? {
    deleteAllRunsDisabled: true,
    historySummaryText: "No runs yet.",
    table: null,
  };
  const t = useUiTranslation();

  return (
    <>
      <div class="history-toolbar">
        <div class="history-toolbar__copy">
            <div id="historySummary" class="history-toolbar__summary subtle">
            {model.historySummaryText}
            </div>
        </div>
        <div class="history-toolbar__actions">
          <button
            id="refreshHistoryBtn"
            class="btn btn--muted"
            type="button"

            onClick={() => state.actions?.onRefreshHistory()}
          >
            {t("history.refresh", "Refresh History")}
          </button>
          <button
            id="deleteAllRunsBtn"
            class="btn btn--danger-quiet"
            type="button"

            disabled={model.deleteAllRunsDisabled}
            onClick={() => state.actions?.onDeleteAllRuns()}
          >
            {t("history.delete_all", "Delete All Runs")}
          </button>
        </div>
      </div>
      <table class="history-table">
        <thead>
          <tr>
            <th>{t("history.table.file", "Run")}</th>
            <th>{t("history.table.updated", "Started")}</th>
            <th class="numeric">
              {t("history.table.size", "Samples")}
            </th>
            <th>{t("history.table.actions", "Actions")}</th>
          </tr>
        </thead>
        <tbody id="historyTableBody">
          <HistoryTableBody handlers={state.actions} table={model.table} />
        </tbody>
      </table>
    </>
  );
}

export function mountHistoryPanel(host: HTMLElement): HistoryPanelView {
  const state = signal<HistoryPanelBridgeState>({ ...DEFAULT_PANEL_STATE });
  render(<HistoryPanel state={state} />, host);

  return {
    bindModel(model: ReadonlySignal<HistoryPanelRenderModel>): void {
      state.value = { ...state.value, model };
    },
    bindActions(handlers: HistoryPanelActionHandlers): void {
      state.value = { ...state.value, actions: handlers };
    },
  };
}
