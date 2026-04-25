import { beforeEach, describe, expect, test } from "vitest";
import { defaultLiveAnalysisConfig } from "../src/constants";
import { runDemoMode } from "../src/app/demo_mode";
import { createAppState } from "../src/app/ui_app_state";
import { adaptServerPayload } from "../src/server_payload";
import { installWindowGlobal } from "./async_test_helpers";

describe("runDemoMode", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("queues a schema-valid websocket payload into shared transport state", () => {
    const selectedClientId = "aabbcc001122";
    const state = createAppState();
    state.transport.wsState.value = "reconnecting";
    let queuedPayload: unknown = null;

    runDemoMode({
      ingestTransportPayload: (payload) => {
        queuedPayload = payload;
      },
      state,
    });

    const adaptedPayload = adaptServerPayload(queuedPayload);

    expect(state.transport.wsState.value).toBe("reconnecting");
    expect(state.transport.hasReceivedPayload.value).toBe(false);
    expect(state.transport.pendingPayload.value).toBeNull();
    expect(adaptedPayload.clients).toHaveLength(5);
    expect(
      adaptedPayload.clients.every(
        (client) => client.sample_rate_hz === defaultLiveAnalysisConfig.sampleRateHz,
      ),
    ).toBe(true);
    expect(adaptedPayload.spectra?.clients[selectedClientId]).toMatchObject({
      freq: expect.any(Array),
      combined: expect.any(Array),
      strength_metrics: expect.objectContaining({
        vibration_strength_db: expect.any(Number),
      }),
    });
  });
});
