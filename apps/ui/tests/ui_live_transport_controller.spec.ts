import { expect, test } from "@playwright/test";

import { EXPECTED_SCHEMA_VERSION, type LiveWsPayload } from "../src/contracts/ws_payload_types";
import { UiLiveTransportController } from "../src/app/runtime/ui_live_transport_controller";
import { createAppState } from "../src/app/ui_app_state";
import { signal } from "../src/app/ui_signals";
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

function installLocation(search: string): () => void {
  const target = window as Window & typeof globalThis & { location?: Location };
  const previousLocation = target.location;
  target.location = {
    search,
    protocol: "http:",
    host: "localhost",
  } as Location;
  return () => {
    if (previousLocation === undefined) {
      delete target.location;
      return;
    }
    target.location = previousLocation;
  };
}

test.describe("UiLiveTransportController", () => {
  test.beforeEach(() => {
    installWindowGlobal();
  });

  test("applies queued transport payloads through shared state without transport ports", async () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    state.transport.ws.value = {
      uiState: signal("connecting"),
      close() {},
      connect() {},
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as typeof state.transport.ws.value;

    new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    const raf = installRafHarness();
    try {
      state.transport.pendingPayload.value = makeLivePayload({
        clients: [makeClient("client-1")],
        speed_mps: 12,
      });
      await flushAsyncWork();
      raf.flushNext();
      await flushAsyncWork();

      expect(state.transport.pendingPayload.value).toBeNull();
      expect(state.realtime.clients.value.map((client) => client.id)).toEqual(["client-1"]);
      expect(state.realtime.selectedClientId.value).toBe("client-1");
      expect(state.realtime.speedMps.value).toBe(12);
      expect(sentSelections).toEqual([{ client_id: "client-1" }]);
    } finally {
      raf.restore();
    }
  });

  test("does not queue an initial payload that already exists before effects bind", async () => {
    const state = createAppState();
    state.transport.pendingPayload.value = makeLivePayload({
      clients: [makeClient("client-1")],
      speed_mps: 12,
    });

    const raf = installRafHarness();
    try {
      new UiLiveTransportController({
        state,
        payloadErrorMessage: () => "payload error",
      });
      await flushAsyncWork();

      expect(state.transport.renderQueued.value).toBe(false);
      expect(state.realtime.clients.value).toEqual([]);
      expect(state.realtime.selectedClientId.value).toBeNull();
      expect(state.realtime.speedMps.value).toBeNull();
    } finally {
      raf.restore();
    }
  });

  test("sends the current client selection when websocket state becomes ready", async () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    const wsUiState = signal("connecting");
    state.transport.ws.value = {
      uiState: wsUiState,
      close() {},
      connect() {},
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as typeof state.transport.ws.value;
    state.realtime.selectedClientId.value = "client-7";

    new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    wsUiState.value = "no_data";
    await flushAsyncWork();
    wsUiState.value = "connected";
    await flushAsyncWork();
    wsUiState.value = "stale";
    await flushAsyncWork();

    expect(sentSelections).toEqual([
      { client_id: "client-7" },
      { client_id: "client-7" },
    ]);
  });

  test("does not send the current selection for an initial ready websocket state", async () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    state.transport.ws.value = {
      uiState: signal("connected"),
      close() {},
      connect() {},
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as typeof state.transport.ws.value;
    state.realtime.selectedClientId.value = "client-7";

    new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });
    await flushAsyncWork();

    expect(sentSelections).toEqual([]);
  });

  test("mirrors ws client uiState into the transport slice", async () => {
    const state = createAppState();
    const wsUiState = signal("connecting");
    state.transport.ws.value = {
      uiState: wsUiState,
      close() {},
      connect() {},
      send() {},
    } as typeof state.transport.ws.value;

    new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    wsUiState.value = "no_data";
    await flushAsyncWork();
    expect(state.transport.wsState.value).toBe("no_data");

    wsUiState.value = "connected";
    await flushAsyncWork();
    expect(state.transport.wsState.value).toBe("connected");
  });

  test("applies payloads without requiring feature-port attachment", () => {
    const state = createAppState();
    const controller = new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });

    expect(() => applyPayload(controller, makeLivePayload())).not.toThrow();
    expect(state.realtime.speedMps.value).toBe(10);
  });

  test("routes demo mode through the shared queued transport pipeline", async () => {
    const state = createAppState();
    const controller = new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
    });
    const restoreLocation = installLocation("?demo=1");
    const raf = installRafHarness();
    try {
      controller.startTransportMode();
      await flushAsyncWork();

      expect(state.transport.wsState.value).toBe("connected");
      expect(state.transport.hasReceivedPayload.value).toBe(true);
      expect(state.transport.pendingPayload.value).not.toBeNull();

      raf.flushNext();
      await flushAsyncWork();

      expect(state.transport.pendingPayload.value).toBeNull();
      expect(state.realtime.clients.value).toHaveLength(5);
      expect(state.realtime.selectedClientId.value).toBe("aabbcc001122");
      expect(state.realtime.speedMps.value).toBe(22.2);
      expect(state.spectrum.hasSpectrumData.value).toBe(true);
    } finally {
      restoreLocation();
      raf.restore();
    }
  });
});
