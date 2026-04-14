import { getById, requiredById } from "./dom_query";

const REALTIME_OWNER = "Realtime feature";
const LIVE_OVERVIEW_HOST_ID = "liveOverviewRoot";

export interface UiRealtimeDom {
  loggingStatus: HTMLElement | null;
  loggingSummary: HTMLElement | null;
  loggingChecklist: HTMLElement | null;
  loggingRunId: HTMLElement | null;
  loggingPhase: HTMLElement | null;
  loggingElapsed: HTMLElement | null;
  loggingSamples: HTMLElement | null;
  startLoggingBtn: HTMLButtonElement;
  stopLoggingBtn: HTMLButtonElement | null;
  sensorsSettingsBody: HTMLElement | null;
  shellLiveStatus: HTMLElement | null;
}

export function getUiLiveOverviewHost(): HTMLElement {
  return requiredById<HTMLElement>(LIVE_OVERVIEW_HOST_ID, REALTIME_OWNER);
}

export function createUiRealtimeDom(): UiRealtimeDom {
  return {
    loggingStatus: getById<HTMLElement>("loggingStatus"),
    loggingSummary: getById<HTMLElement>("loggingSummary"),
    loggingChecklist: getById<HTMLElement>("loggingChecklist"),
    loggingRunId: getById<HTMLElement>("loggingRunId"),
    loggingPhase: getById<HTMLElement>("loggingPhase"),
    loggingElapsed: getById<HTMLElement>("loggingElapsed"),
    loggingSamples: getById<HTMLElement>("loggingSamples"),
    startLoggingBtn: requiredById<HTMLButtonElement>("startLoggingBtn", REALTIME_OWNER),
    stopLoggingBtn: getById<HTMLButtonElement>("stopLoggingBtn"),
    sensorsSettingsBody: getById<HTMLElement>("sensorsSettingsBody"),
    shellLiveStatus: getById<HTMLElement>("shellLiveStatus"),
  };
}
