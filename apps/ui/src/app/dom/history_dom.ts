import { requiredById } from "./dom_query";

const HISTORY_OWNER = "History feature";
const HISTORY_PANEL_HOST_ID = "historyPanelRoot";

export function getUiHistoryPanelHost(): HTMLElement {
  return requiredById<HTMLElement>(HISTORY_PANEL_HOST_ID, HISTORY_OWNER);
}
