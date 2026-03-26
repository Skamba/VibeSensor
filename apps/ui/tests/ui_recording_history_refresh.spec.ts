import { expect, test } from "@playwright/test";

import { createUiRecordingHistoryRefresh } from "../src/app/runtime/ui_recording_history_refresh";

test.describe("createUiRecordingHistoryRefresh", () => {
  test("delegates post-recording refresh through the narrow runtime seam", async () => {
    const calls: string[] = [];
    const refresh = createUiRecordingHistoryRefresh({
      refreshHistory: async () => {
        calls.push("refreshHistory");
      },
    });

    await refresh.onRecordingStatusChanged();

    expect(calls).toEqual(["refreshHistory"]);
  });

  test("preserves refresh failures so realtime can surface them", async () => {
    const error = new Error("history refresh failed");
    const refresh = createUiRecordingHistoryRefresh({
      refreshHistory: async () => {
        throw error;
      },
    });

    await expect(refresh.onRecordingStatusChanged()).rejects.toThrow(error);
  });
});
