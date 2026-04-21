import { expect, test } from "vitest";
import {
  createAppFeatureBundlePorts,
  createRealtimeFeatureRecordingPorts,
} from "../src/app/app_feature_bundle_ports";

test("feature port helpers expose the narrowed shell and startup contracts", async () => {
  const calls: string[] = [];

  const history = {
    async refreshHistory() {
      calls.push("history.refreshHistory");
    },
  };
  const realtime = {
    bindHandlers() {
      calls.push("realtime.bindHandlers");
    },
    dispose() {
      calls.push("realtime.dispose");
    },
    async refreshLocationOptions() {
      calls.push("realtime.refreshLocationOptions");
    },
    async refreshLoggingStatus() {
      calls.push("realtime.refreshLoggingStatus");
    },
  };
  const secondary = {
    dispose() {
      calls.push("secondary.dispose");
    },
  };

  const recording = createRealtimeFeatureRecordingPorts(history);
  const bundle = createAppFeatureBundlePorts({
    realtime,
    secondary,
  });

  expect(Object.keys(bundle).sort()).toEqual(["dispose", "ensureViewReady", "shell", "startup"]);

  await recording.onRecordingStatusChanged();

  bundle.shell.bindHandlers();
  await bundle.ensureViewReady("historyView");

  await bundle.startup.realtime.refreshLocationOptions();
  await bundle.startup.realtime.refreshLoggingStatus();
  bundle.dispose();

  expect(calls).toEqual([
    "history.refreshHistory",
    "realtime.bindHandlers",
    "realtime.refreshLocationOptions",
    "realtime.refreshLoggingStatus",
    "secondary.dispose",
    "realtime.dispose",
  ]);
});

test("realtime recording port preserves history refresh failures", async () => {
  const error = new Error("history refresh failed");
  const recording = createRealtimeFeatureRecordingPorts({
    async refreshHistory() {
      throw error;
    },
  });

  await expect(recording.onRecordingStatusChanged()).rejects.toThrow(error);
});
