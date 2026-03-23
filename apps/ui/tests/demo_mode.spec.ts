import { expect, test } from "@playwright/test";

import { runDemoMode } from "../src/app/demo_mode";
import { adaptServerPayload } from "../src/server_payload";

test.describe("runDemoMode", () => {
  test.beforeEach(() => {
    (globalThis as { window?: Window & typeof globalThis }).window = globalThis as unknown as Window &
      typeof globalThis;
  });

  test("emits a schema-valid websocket payload", () => {
    const selectedClientId = "aabbcc001122";
    const state = {
      transport: {
        wsState: "disconnected",
        hasReceivedPayload: false,
      },
    };
    let renderWsStateCalls = 0;
    let adaptedPayload:
      | ReturnType<typeof adaptServerPayload>
      | undefined;

    runDemoMode({
      state,
      renderWsState: () => {
        renderWsStateCalls += 1;
      },
      applyPayload: (payload) => {
        adaptedPayload = adaptServerPayload(payload);
      },
    });

    expect(renderWsStateCalls).toBe(1);
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
