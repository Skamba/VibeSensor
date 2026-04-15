import { expect, test } from "@playwright/test";

import { EXPECTED_SCHEMA_VERSION, type LiveWsPayload } from "../src/contracts/ws_payload_types";
import { UiLiveTransportController, type UiTransportFeaturePorts } from "../src/app/runtime/ui_live_transport_controller";
import { createAppState } from "../src/app/ui_app_state";
import { flushAsyncWork, installWindowGlobal } from "./async_test_helpers";

function makeLivePayload(overrides: Partial<LiveWsPayload> = {}): LiveWsPayload {
  return {
    schema_version: EXPECTED_SCHEMA_VERSION,
    server_time: "2026-01-01T00:00:00Z",
    clients: [],
    selected_client_id: null,
    rotational_speeds: null,
    speed_mps: 10,
    ...overrides,
  };
}

function makeClient(id: string): LiveWsPayload["clients"][number] {
  return {
    id,
    name: `Sensor ${id}`,
    connected: true,
    mac_address: `00:11:22:33:44:${id.slice(-2).padStart(2, "0")}`,
    location_code: "",
    last_seen_age_ms: 0,
    dropped_frames: 0,
    frames_total: 1,
    sample_rate_hz: 1600,
    firmware_version: "1.0.0",
  };
}

function applyPayload(controller: UiLiveTransportController, payload: LiveWsPayload): void {
  (controller as unknown as { applyPayload(nextPayload: LiveWsPayload): void }).applyPayload(payload);
}

function installRafHarness() {
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
  const callbacks: FrameRequestCallback[] = [];
  globalThis.requestAnimationFrame = ((callback: FrameRequestCallback) => {
    callbacks.push(callback);
    return callbacks.length as unknown as number;
  }) as typeof requestAnimationFrame;
  return {
    flushNext(): void {
      const callback = callbacks.shift();
      if (!callback) {
        throw new Error("No pending animation frame");
      }
      callback(Date.now());
    },
    restore(): void {
      globalThis.requestAnimationFrame = originalRequestAnimationFrame;
    },
  };
}

test.describe("UiLiveTransportController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("applies queued transport payloads through narrow transport ports without an AppFeatureBundle", async () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    state.transport.ws = {
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as unknown as typeof state.transport.ws;

    const controller = new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    const portCalls: string[] = [];
    const renderedStatusIds: Array<string | null> = [];
    const ports = {
      updateClientSelection(): void {
        portCalls.push("updateClientSelection");
        state.realtime.selectedClientId = state.realtime.clients[0]?.id ?? null;
      },
      maybeRenderSensorsSettingsList(): void {
        portCalls.push("maybeRenderSensorsSettingsList");
      },
      renderLoggingStatus(): void {
        portCalls.push("renderLoggingStatus");
      },
      renderStatus(clientRow): void {
        portCalls.push("renderStatus");
        renderedStatusIds.push(clientRow?.id ?? null);
      },
    } satisfies UiTransportFeaturePorts;

    const raf = installRafHarness();
    try {
      controller.attachPorts(ports);
      state.transport.pendingPayload = makeLivePayload({
        clients: [makeClient("client-1")],
        speed_mps: 12,
      });
      await flushAsyncWork();
      raf.flushNext();

      expect(state.transport.pendingPayload).toBeNull();
      expect(state.realtime.clients.map((client) => client.id)).toEqual(["client-1"]);
      expect(state.realtime.selectedClientId).toBe("client-1");
      expect(state.realtime.speedMps).toBe(12);
      expect(portCalls).toEqual([
        "updateClientSelection",
        "maybeRenderSensorsSettingsList",
        "renderLoggingStatus",
        "renderStatus",
      ]);
      expect(renderedStatusIds).toEqual(["client-1"]);
      expect(sentSelections).toEqual([{ client_id: "client-1" }]);
    } finally {
      raf.restore();
    }
  });

  test("sends the current client selection when websocket state becomes ready", async () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    state.transport.ws = {
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as unknown as typeof state.transport.ws;
    state.realtime.selectedClientId = "client-7";

    new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    state.transport.wsState = "no_data";
    await flushAsyncWork();
    state.transport.wsState = "connected";
    await flushAsyncWork();
    state.transport.wsState = "stale";
    await flushAsyncWork();

    expect(sentSelections).toEqual([
      { client_id: "client-7" },
      { client_id: "client-7" },
    ]);
  });

  test("throws a clear error when payloads arrive before ports are attached", () => {
    const controller = new UiLiveTransportController({
      state: createAppState(),
      payloadErrorMessage: () => "payload error",
    });

    expect(() => applyPayload(controller, makeLivePayload())).toThrow(
      "UiLiveTransportController ports used before initialization",
    );
  });
});
