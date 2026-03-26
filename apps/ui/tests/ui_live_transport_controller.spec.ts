import { expect, test } from "@playwright/test";

import { EXPECTED_SCHEMA_VERSION, type LiveWsPayload } from "../src/contracts/ws_payload_types";
import { UiLiveTransportController, type UiTransportFeaturePorts } from "../src/app/runtime/ui_live_transport_controller";
import { createAppState } from "../src/app/ui_app_state";

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

test.describe("UiLiveTransportController", () => {
  test("applies payloads through narrow transport ports without an AppFeatureBundle", () => {
    const state = createAppState();
    const sentSelections: Array<{ client_id: string | null }> = [];
    state.transport.ws = {
      send(selection: { client_id: string | null }) {
        sentSelections.push(selection);
      },
    } as unknown as typeof state.transport.ws;

    let renderWsStateCalls = 0;
    let renderSpeedReadoutCalls = 0;
    let renderSpectrumCalls = 0;
    let updateSpectrumOverlayCalls = 0;

    const controller = new UiLiveTransportController({
      state,
      payloadErrorMessage: () => "payload error",
      renderWsState: () => {
        renderWsStateCalls += 1;
      },
      renderSpeedReadout: () => {
        renderSpeedReadoutCalls += 1;
      },
      renderSpectrum: () => {
        renderSpectrumCalls += 1;
      },
      updateSpectrumOverlay: () => {
        updateSpectrumOverlayCalls += 1;
      },
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

    controller.attachPorts(ports);
    applyPayload(controller, makeLivePayload({
      clients: [makeClient("client-1")],
      speed_mps: 12,
    }));

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
    expect(renderWsStateCalls).toBe(1);
    expect(renderSpeedReadoutCalls).toBe(1);
    expect(renderSpectrumCalls).toBe(0);
    expect(updateSpectrumOverlayCalls).toBe(1);
    expect(sentSelections).toEqual([{ client_id: "client-1" }]);
  });

  test("throws a clear error when payloads arrive before ports are attached", () => {
    const controller = new UiLiveTransportController({
      state: createAppState(),
      payloadErrorMessage: () => "payload error",
      renderWsState: () => undefined,
      renderSpeedReadout: () => undefined,
      renderSpectrum: () => undefined,
      updateSpectrumOverlay: () => undefined,
    });

    expect(() => applyPayload(controller, makeLivePayload())).toThrow(
      "UiLiveTransportController ports used before initialization",
    );
  });
});
