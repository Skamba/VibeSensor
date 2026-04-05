import { getById, requiredById } from "./dom_query";

const HISTORY_OWNER = "History feature";

export interface UiHistoryDom {
  refreshHistoryBtn: HTMLButtonElement | null;
  deleteAllRunsBtn: HTMLButtonElement | null;
  historySummary: HTMLElement | null;
  historyTableBody: HTMLElement;
}

export function createUiHistoryDom(): UiHistoryDom {
  return {
    refreshHistoryBtn: getById<HTMLButtonElement>("refreshHistoryBtn"),
    deleteAllRunsBtn: getById<HTMLButtonElement>("deleteAllRunsBtn"),
    historySummary: getById<HTMLElement>("historySummary"),
    historyTableBody: requiredById<HTMLElement>("historyTableBody", HISTORY_OWNER),
  };
}
