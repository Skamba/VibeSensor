import { expect, test } from "@playwright/test";

import { runDemoMode } from "../src/app/demo_mode";
import { createAppState } from "../src/app/ui_app_state";
import { adaptServerPayload } from "../src/server_payload";
import { installWindowGlobal } from "./async_test_helpers";

test.describe("runDemoMode", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("emits a schema-valid websocket payload", () => {
    const selectedClientId = "aabbcc001122";
    const state = createAppState();
    state.transport.wsState = "reconnecting";
    let adaptedPayload:
      | ReturnType<typeof adaptServerPayload>
      | undefined;

    runDemoMode({
      state,
      applyPayload: (payload) => {
        adaptedPayload = adaptServerPayload(payload);
      },
    });

    expect(state.transport.wsState).toBe("connected");
    expect(state.transport.hasReceivedPayload).toBe(true);
    expect(adaptedPayload).toBeDefined();
    expect(adaptedPayload?.clients).toHaveLength(5);
    expect(adaptedPayload?.spectra?.clients[selectedClientId]).toMatchObject({
      freq: expect.any(Array),
      combined: expect.any(Array),
      strength_metrics: expect.objectContaining({
        vibration_strength_db: expect.any(Number),
      }),
    });
  });
});
