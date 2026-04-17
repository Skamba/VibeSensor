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
    let queuedPayload: unknown = null;

    runDemoMode({
      queueTransportPayload: (payload) => {
        queuedPayload = payload;
      },
      state,
    });

    const adaptedPayload = adaptServerPayload(queuedPayload);

    expect(state.transport.wsState).toBe("reconnecting");
    expect(state.transport.hasReceivedPayload).toBe(false);
    expect(unwrapAppStateValue(state.transport.pendingPayload)).toBeNull();
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
