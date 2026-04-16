import { expect, test } from "@playwright/test";

import { createRealtimeFeatureViewState } from "../src/app/features/realtime_feature_view_state";
import { createRealtimeFeatureWorkflowState } from "../src/app/features/realtime_feature_workflow";
import { createAppState } from "../src/app/ui_app_state";

test("realtime view state only re-arms its elapsed timer when logging tick inputs change", () => {
  const state = createAppState();
  const workflow = createRealtimeFeatureWorkflowState();
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  const createdTimerIds: Array<ReturnType<typeof setInterval>> = [];
  const activeTimerIds = new Set<ReturnType<typeof setInterval>>();
  const clearedTimerIds: Array<ReturnType<typeof setInterval>> = [];

  globalThis.setInterval = ((handler: TimerHandler, timeout?: number) => {
    void handler;
    void timeout;
    const timerId = originalSetInterval(() => undefined, 60_000);
    originalClearInterval(timerId);
    createdTimerIds.push(timerId);
    activeTimerIds.add(timerId);
    return timerId;
  }) as typeof setInterval;
  globalThis.clearInterval = ((intervalId?: ReturnType<typeof setInterval>) => {
    if (intervalId === undefined) {
      return;
    }
    clearedTimerIds.push(intervalId);
    activeTimerIds.delete(intervalId);
  }) as typeof clearInterval;

  try {
    createRealtimeFeatureViewState({
      state: {
        realtime: state.realtime,
        settings: state.settings,
        shell: state.shell,
        spectrum: state.spectrum,
      },
      services: {
        t: (key) => key,
      },
      formatting: {
        formatInt: (value) => String(value),
      },
      workflow,
    });

    expect(activeTimerIds.size).toBe(0);

    workflow.handlersBound.value = true;
    state.realtime.loggingStatus.enabled = true;
    state.realtime.loggingStatus.start_time_utc = "2026-04-16T00:00:00Z";

    expect(createdTimerIds).toHaveLength(1);
    expect(Array.from(activeTimerIds)).toEqual([createdTimerIds[0]]);
    expect(clearedTimerIds).toEqual([]);

    state.realtime.selectedClientId = "sensor-1";

    expect(createdTimerIds).toHaveLength(1);
    expect(Array.from(activeTimerIds)).toEqual([createdTimerIds[0]]);
    expect(clearedTimerIds).toEqual([]);

    state.realtime.loggingStatus.start_time_utc = "2026-04-16T00:00:05Z";

    expect(createdTimerIds).toHaveLength(2);
    expect(Array.from(activeTimerIds)).toEqual([createdTimerIds[1]]);
    expect(clearedTimerIds).toEqual([createdTimerIds[0]]);

    state.realtime.loggingStatus.enabled = false;

    expect(activeTimerIds.size).toBe(0);
    expect(clearedTimerIds).toEqual([createdTimerIds[0], createdTimerIds[1]]);
  } finally {
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  }
});

test("realtime view state preserves the last completed elapsed text through processing and saved states", () => {
  const state = createAppState();
  const workflow = createRealtimeFeatureWorkflowState();
  const originalDateNow = Date.now;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;

  Date.now = () => Date.parse("2026-04-16T00:01:23Z");
  globalThis.setInterval = ((handler: TimerHandler, timeout?: number) => {
    void handler;
    void timeout;
    const timerId = originalSetInterval(() => undefined, 60_000);
    originalClearInterval(timerId);
    return timerId;
  }) as typeof setInterval;
  globalThis.clearInterval = ((intervalId?: ReturnType<typeof setInterval>) => {
    if (intervalId === undefined) {
      return;
    }
  }) as typeof clearInterval;

  try {
    const viewState = createRealtimeFeatureViewState({
      state: {
        realtime: state.realtime,
        settings: state.settings,
        shell: state.shell,
        spectrum: state.spectrum,
      },
      services: {
        t: (key) => key,
      },
      formatting: {
        formatInt: (value) => String(value),
      },
      workflow,
    });

    workflow.handlersBound.value = true;
    state.realtime.loggingStatus = {
      ...state.realtime.loggingStatus,
      enabled: true,
      start_time_utc: "2026-04-16T00:00:00Z",
      last_completed_run_id: null,
    };

    expect(viewState.loggingPanelModel.value.elapsedText).toBe("1:23");

    state.realtime.loggingStatus = {
      ...state.realtime.loggingStatus,
      enabled: false,
      analysis_in_progress: true,
      start_time_utc: null,
      last_completed_run_id: "run-1",
    };

    expect(viewState.loggingPanelModel.value.elapsedText).toBe("1:23");

    state.realtime.loggingStatus = {
      ...state.realtime.loggingStatus,
      analysis_in_progress: false,
    };

    expect(viewState.loggingPanelModel.value.elapsedText).toBe("1:23");

    state.realtime.loggingStatus = {
      ...state.realtime.loggingStatus,
      last_completed_run_id: null,
    };

    expect(viewState.loggingPanelModel.value.elapsedText).toBe("--");
  } finally {
    Date.now = originalDateNow;
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
  }
});
