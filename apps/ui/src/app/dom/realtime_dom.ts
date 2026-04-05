import { getById, requiredById } from "./dom_query";

const REALTIME_OWNER = "Realtime feature";

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
  liveConnectedSensors: HTMLElement | null;
  liveActiveCar: HTMLElement | null;
  liveRecordingState: HTMLElement | null;
  liveDataFreshness: HTMLElement | null;
  liveStrongestSignal: HTMLElement | null;
  liveRunHealth: HTMLElement | null;
  liveSensorRoster: HTMLElement | null;
  shellLiveStatus: HTMLElement | null;
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
    liveConnectedSensors: getById<HTMLElement>("liveConnectedSensors"),
    liveActiveCar: getById<HTMLElement>("liveActiveCar"),
    liveRecordingState: getById<HTMLElement>("liveRecordingState"),
    liveDataFreshness: getById<HTMLElement>("liveDataFreshness"),
    liveStrongestSignal: getById<HTMLElement>("liveStrongestSignal"),
    liveRunHealth: getById<HTMLElement>("liveRunHealth"),
    liveSensorRoster: getById<HTMLElement>("liveSensorRoster"),
    shellLiveStatus: getById<HTMLElement>("shellLiveStatus"),
  };
}
