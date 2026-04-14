import { useLayoutEffect, useRef } from "preact/hooks";

import { createUiPreactMount } from "../runtime/ui_preact_mount";
import { getTypedInlineStateAction } from "./dom_helpers";
import {
  getHistoryTableAction,
  getHistoryTableRowRunId,
  renderHistoryEmptyState,
  renderHistoryTable,
  type HistoryPanelActionHandlers,
  type HistoryPanelRenderModel,
  type HistoryPanelView,
} from "./history_table_view";

const HISTORY_INLINE_ACTIONS = ["open-live"] as const;

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
  const tableBodyRef = useRef<HTMLTableSectionElement | null>(null);

  useLayoutEffect(() => {
    const tableBody = tableBodyRef.current;
    if (!tableBody || state.table === null) {
      return;
    }
    if (state.table.kind === "empty") {
      renderHistoryEmptyState(tableBody, {
        t: state.table.t,
      });
      return;
    }
    renderHistoryTable(tableBody, state.table.params);
  }, [state.table]);

  function handleTableClick(event: MouseEvent): void {
    const inlineAction = getTypedInlineStateAction(event.target, HISTORY_INLINE_ACTIONS);
    if (inlineAction) {
      event.preventDefault();
      event.stopPropagation();
      state.actions?.onTableInteraction({ type: inlineAction });
      return;
    }
    const action = getHistoryTableAction(event.target);
    if (action) {
      if (action.action !== "download-raw") {
        event.preventDefault();
      }
      event.stopPropagation();
      state.actions?.onTableInteraction({
        type: "run-action",
        action: action.action,
        runId: action.runId,
      });
      return;
    }
    const runId = getHistoryTableRowRunId(event.target);
    if (runId) {
      state.actions?.onTableInteraction({ type: "toggle-run", runId });
    }
  }

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
        <tbody id="historyTableBody" ref={tableBodyRef} onClick={handleTableClick}>
          {state.table === null
            ? (
              <tr>
                <td colSpan={4}>No runs found.</td>
              </tr>
            )
            : null}
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
