import { expect, test } from "@playwright/test";

import {
  createAppState,
} from "../src/app/ui_app_state";
import { batch, effect } from "../src/app/ui_signals";

test.describe("ui_app_state reactivity", () => {
  test("tracks shell writes directly through field signals without slice tracking", () => {
    const state = createAppState();
    const seenShellState: string[] = [];

    const dispose = effect(() => {
      seenShellState.push(
        `${state.shell.lang.value}:${state.shell.speedUnit.value}:${state.shell.activeViewId.value}`,
      );
    });

    expect(seenShellState).toEqual(["en:kmh:dashboardView"]);

    batch(() => {
      state.shell.lang.value = "nl";
      state.shell.speedUnit.value = "mps";
      state.shell.activeViewId.value = "historyView";
    });

    expect(seenShellState).toEqual([
      "en:kmh:dashboardView",
      "nl:mps:historyView",
    ]);

    dispose();
  });

  test("tracks transport writes directly through stable field signals", () => {
    const state = createAppState();
    const seenStates: string[] = [];

    const wsStateSignal = state.transport.wsState;
    expect(state.transport.wsState).toBe(wsStateSignal);

    const dispose = effect(() => {
      seenStates.push(`${state.transport.wsState.value}:${String(state.transport.payloadError.value)}`);
    });

    expect(seenStates).toEqual(["connecting:null"]);

    state.transport.wsState.value = "connected";
    state.transport.payloadError.value = "boom";

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
      seenRatios.push(state.settings.car.activeVehicleSettings.value.current_gear_ratio);
    });

    expect(seenRatios).toEqual([0.64]);

    state.settings.car.activeVehicleSettings.value = {
      ...state.settings.car.activeVehicleSettings.value,
      current_gear_ratio: 0.72,
    };

    expect(seenRatios).toEqual([0.64, 0.72]);

    dispose();
  });

  test("keeps slice notifications isolated", () => {
    const state = createAppState();
    let transportRuns = 0;
    let settingsRuns = 0;

    const disposeTransport = effect(() => {
      transportRuns += 1;
      void state.transport.wsState.value;
    });
    const disposeSettings = effect(() => {
      settingsRuns += 1;
      void state.settings.analysis.vehicleSettings.value;
    });

    expect(transportRuns).toBe(1);
    expect(settingsRuns).toBe(1);

    state.transport.wsState.value = "stale";

    expect(transportRuns).toBe(2);
    expect(settingsRuns).toBe(1);

    disposeTransport();
    disposeSettings();
  });

  test("batches multi-field writes into one reactive invalidation", () => {
    const state = createAppState();
    const seenSnapshots: string[] = [];

    const dispose = effect(() => {
      seenSnapshots.push(
        `${state.transport.wsState.value}:${String(state.transport.hasReceivedPayload.value)}:${String(state.transport.payloadError.value)}`,
      );
    });

    expect(seenSnapshots).toEqual(["connecting:false:null"]);

    batch(() => {
      state.transport.wsState.value = "connected";
      state.transport.hasReceivedPayload.value = true;
      state.transport.payloadError.value = "frame-error";
    });

    expect(seenSnapshots).toEqual([
      "connecting:false:null",
      "connected:true:frame-error",
    ]);

    dispose();
  });
});
