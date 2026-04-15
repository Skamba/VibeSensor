import { expect, test } from "@playwright/test";

import { runDemoMode } from "../src/app/demo_mode";
import { createAppState, unwrapAppStateValue } from "../src/app/ui_app_state";
import { adaptServerPayload } from "../src/server_payload";
import { installWindowGlobal } from "./async_test_helpers";

test.describe("runDemoMode", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("queues a schema-valid websocket payload into shared transport state", () => {
    const selectedClientId = "aabbcc001122";
    const state = createAppState();
    state.transport.wsState = "reconnecting";

    runDemoMode({
      state,
    });

    const adaptedPayload = adaptServerPayload(
      unwrapAppStateValue(state.transport.pendingPayload),
    );

    expect(state.transport.wsState).toBe("connected");
    expect(state.transport.hasReceivedPayload).toBe(true);
    expect(state.transport.pendingPayload).not.toBeNull();
    expect(adaptedPayload.clients).toHaveLength(5);
    expect(adaptedPayload.spectra?.clients[selectedClientId]).toMatchObject({
      freq: expect.any(Array),
      combined: expect.any(Array),
      strength_metrics: expect.objectContaining({
        vibration_strength_db: expect.any(Number),
      }),
    });
  });
});
