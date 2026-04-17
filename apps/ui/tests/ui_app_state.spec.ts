import { expect, test } from "@playwright/test";

import {
  batchAppStateUpdates,
  createAppState,
  getAppStateSliceSignal,
  trackAppStateSlice,
} from "../src/app/ui_app_state";
import { effect } from "../src/app/ui_signals";

test.describe("ui_app_state reactivity", () => {
  test("tracks shell writes directly through field signals without slice tracking", () => {
    const state = createAppState();
    const seenShellState: string[] = [];

    const dispose = effect(() => {
      seenShellState.push(`${state.shell.lang}:${state.shell.speedUnit}:${state.shell.activeViewId}`);
    });

    expect(seenShellState).toEqual(["en:kmh:dashboardView"]);

    batchAppStateUpdates(() => {
      state.shell.lang = "nl";
      state.shell.speedUnit = "mps";
      state.shell.activeViewId = "historyView";
    });

    expect(seenShellState).toEqual([
      "en:kmh:dashboardView",
      "nl:mps:historyView",
    ]);

    dispose();
  });

  test("tracks direct slice writes through a stable slice signal", () => {
    const state = createAppState();
    const seenStates: string[] = [];

    const transportSignal = getAppStateSliceSignal(state.transport);
    expect(getAppStateSliceSignal(state.transport)).toBe(transportSignal);

    const dispose = effect(() => {
      trackAppStateSlice(state.transport);
      seenStates.push(`${state.transport.wsState}:${String(state.transport.payloadError)}`);
    });

    expect(seenStates).toEqual(["connecting:null"]);

    state.transport.wsState = "connected";
    state.transport.payloadError = "boom";

    expect(seenStates).toEqual([
      "connecting:null",
      "connected:null",
      "connected:boom",
    ]);

    dispose();
  });

  test("tracks nested object writes within a slice", () => {
    const state = createAppState();
    const seenRatios: number[] = [];

    const dispose = effect(() => {
      trackAppStateSlice(state.settings);
      seenRatios.push(state.settings.vehicleSettings.current_gear_ratio);
    });

    expect(seenRatios).toEqual([0.64]);

    state.settings.vehicleSettings.current_gear_ratio = 0.72;

    expect(seenRatios).toEqual([0.64, 0.72]);

    dispose();
  });

  test("keeps slice notifications isolated", () => {
    const state = createAppState();
    let transportRuns = 0;
    let settingsRuns = 0;

    const disposeTransport = effect(() => {
      trackAppStateSlice(state.transport);
      transportRuns += 1;
    });
    const disposeSettings = effect(() => {
      trackAppStateSlice(state.settings);
      settingsRuns += 1;
    });

    expect(transportRuns).toBe(1);
    expect(settingsRuns).toBe(1);

    state.transport.wsState = "stale";

    expect(transportRuns).toBe(2);
    expect(settingsRuns).toBe(1);

    disposeTransport();
    disposeSettings();
  });

  test("batches multi-field writes into one reactive invalidation", () => {
    const state = createAppState();
    const seenSnapshots: string[] = [];

    const dispose = effect(() => {
      trackAppStateSlice(state.transport);
      seenSnapshots.push(
        `${state.transport.wsState}:${String(state.transport.hasReceivedPayload)}:${String(state.transport.payloadError)}`,
      );
    });

    expect(seenSnapshots).toEqual(["connecting:false:null"]);

    batchAppStateUpdates(() => {
      state.transport.wsState = "connected";
      state.transport.hasReceivedPayload = true;
      state.transport.payloadError = "frame-error";
    });

    expect(seenSnapshots).toEqual([
      "connecting:false:null",
      "connected:true:frame-error",
    ]);

    dispose();
  });
});
