import { getById, requiredById } from "./dom_query";

const REALTIME_OWNER = "Realtime feature";
const LIVE_OVERVIEW_HOST_ID = "liveOverviewRoot";
const LOGGING_PANEL_HOST_ID = "loggingPanelRoot";

export interface UiRealtimeDom {
  shellLiveStatus: HTMLElement | null;
}

export function getUiLiveOverviewHost(): HTMLElement {
  return requiredById<HTMLElement>(LIVE_OVERVIEW_HOST_ID, REALTIME_OWNER);
}

export function getUiLoggingPanelHost(): HTMLElement {
  return requiredById<HTMLElement>(LOGGING_PANEL_HOST_ID, REALTIME_OWNER);
}

export function createUiRealtimeDom(): UiRealtimeDom {
  return {
    shellLiveStatus: getById<HTMLElement>("shellLiveStatus"),
  };
}
