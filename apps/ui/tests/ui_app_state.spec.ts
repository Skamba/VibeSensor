import { expect, test } from "@playwright/test";

import { createAppState } from "../src/app/ui_app_state";

test("createAppState seeds recording status counters", () => {
  const state = createAppState();

  expect(state.realtime.loggingStatus).toEqual({
    enabled: false,
    run_id: null,
    write_error: null,
    analysis_in_progress: false,
    samples_written: 0,
    samples_dropped: 0,
  });
});
