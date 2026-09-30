import { beforeEach, describe, expect, test, vi } from "vitest";
import type { LoggingStatusPayload } from "../src/api/types";
import { createRealtimeFeature } from "../src/app/features/realtime_feature";
import { createAppState } from "../src/app/ui_app_state";
import { effect, signal } from "../src/app/ui_signals";
import type { AdaptedClient } from "../src/transport/live_models";
import { createTestQueryClient } from "./query_client_test_support";

const api = vi.hoisted(() => ({
  getClientLocations: vi.fn(),
  getLoggingStatus: vi.fn(),
  identifyClient: vi.fn(),
  removeClient: vi.fn(),
  setClientLocation: vi.fn(),
  startLoggingRun: vi.fn(),
  stopLoggingRun: vi.fn(),
}));

vi.mock("../src/api/logging", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/logging")>()),
  getLoggingStatus: api.getLoggingStatus,
  startLoggingRun: api.startLoggingRun,
  stopLoggingRun: api.stopLoggingRun,
}));

vi.mock("../src/api/clients", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/clients")>()),
  getClientLocations: api.getClientLocations,
  identifyClient: api.identifyClient,
  removeClient: api.removeClient,
  setClientLocation: api.setClientLocation,
}));

beforeEach(() => {
  vi.resetAllMocks();
});

type FeatureHarness = {
  state: ReturnType<typeof createAppState>;
  apiCalls: string[];
  selectionCalls: string[];
  recordingCalls: string[];
  confirmMessages: string[];
  confirmResult: boolean;
  showErrors: string[];
};

function makeClient(
  id: string,
  overrides: Partial<AdaptedClient> = {},
): AdaptedClient {
  return {
    id,
    name: id,
    connected: true,
    mac_address: id,
    location_code: "",
    sample_rate_hz: 1000,
    frame_samples: 200,
    dropped_frames: 0,
    frames_total: 100,
    last_seen_age_ms: 10,
    firmware_version: "",
    ...overrides,
  };
}

function createHarness(): FeatureHarness {
  return {
    state: createAppState(),
    apiCalls: [],
    selectionCalls: [],
    recordingCalls: [],
    confirmMessages: [],
    confirmResult: true,
    showErrors: [],
  };
}

/** Builds the controller against fake dashboard/sensor panels. */
function createFeature(harness: FeatureHarness) {
  const { state } = harness;
  return createRealtimeFeature({
    realtime: state.realtime,
    settings: state.settings,
    spectrum: state.spectrum,
    shell: state.shell,
    sensorsPanel: { actions: signal(null), model: signal(null) },
    liveOverview: { model: signal(null), speedText: signal(null) },
    loggingPanel: { actions: signal(null), model: signal(null) },
    setShellLiveStatus: () => undefined,
    navigation: {
      activatePrimaryView: () => undefined,
      activateSettingsTab: () => undefined,
      openCarWizard: () => undefined,
    },
    sendSelection() {
      harness.selectionCalls.push("sendSelection");
    },
    async onRecordingStatusChanged() {
      harness.recordingCalls.push("onRecordingStatusChanged");
    },
    queryClient: createTestQueryClient(),
    services: {
      t: (key, vars) => (vars?.id ? `${key}:${String(vars.id)}` : key),
      showError: (message) => {
        harness.showErrors.push(message);
      },
      requestConfirmation: async (message) => {
        harness.confirmMessages.push(message);
        return harness.confirmResult;
      },
    },
    formatting: { formatInt: (value) => String(value) },
  });
}

describe("createRealtimeFeature", () => {
  test("starts logging through signal-backed workflow state and restarts polling", async () => {
    const harness = createHarness();
    harness.state.realtime.loggingStatus.value = {
      ...harness.state.realtime.loggingStatus.value,
      last_completed_run_id: "previous-run",
    };
    const nextStatus: LoggingStatusPayload = {
      ...harness.state.realtime.loggingStatus.value,
      enabled: true,
      run_id: "run-42",
      start_time_utc: "2026-04-05T09:00:00Z",
      last_completed_run_id: null,
    };
    api.getLoggingStatus.mockImplementation(async () => {
      harness.apiCalls.push("getLoggingStatus");
      return harness.state.realtime.loggingStatus.value;
    });
    api.startLoggingRun.mockImplementation(async () => {
      harness.apiCalls.push("startLoggingRun");
      return nextStatus;
    });
    const workflow = createFeature(harness);
    const pendingTransitions: Array<"starting" | "stopping" | null> = [];
    effect(() => {
      pendingTransitions.push(workflow.signals.pendingLoggingAction.value);
    });

    workflow.bindHandlers();
    await workflow.startLogging();

    expect(harness.recordingCalls).toEqual(["onRecordingStatusChanged"]);
    expect(harness.apiCalls).toContain("startLoggingRun");
    expect(pendingTransitions).toEqual([null, "starting", null]);
    expect(workflow.signals.handlersBound.value).toBe(true);
    expect(workflow.signals.loggingError.value).toBeNull();
    expect(harness.state.realtime.loggingStatus.value).toEqual(nextStatus);
    workflow.dispose();
  });

  test("refreshes idle capture readiness when the connected sensor set changes", async () => {
    const harness = createHarness();
    harness.state.realtime.clients.value = [makeClient("client-a")];
    api.getLoggingStatus.mockImplementation(async () => {
      harness.apiCalls.push(
        `getLoggingStatus:${harness.state.realtime.clients.value.length}`,
      );
      return harness.state.realtime.loggingStatus.value;
    });
    const workflow = createFeature(harness);

    workflow.bindHandlers();

    await expect.poll(() => harness.apiCalls.length).toBeGreaterThanOrEqual(1);
    const initialCalls = harness.apiCalls.length;
    harness.state.realtime.clients.value = [
      makeClient("client-a"),
      makeClient("client-b"),
    ];
    await expect
      .poll(() => harness.apiCalls.length)
      .toBeGreaterThan(initialCalls);
    expect(harness.apiCalls.at(-1)).toBe("getLoggingStatus:2");
    workflow.dispose();
  });

  test("keeps the last known location codes and rejects when refreshing locations fails", async () => {
    const harness = createHarness();
    harness.state.realtime.locationCodes.value = ["custom-code"];
    api.getClientLocations.mockRejectedValue(new Error("network unavailable"));
    const workflow = createFeature(harness);

    await expect(workflow.refreshLocationOptions()).rejects.toThrow(
      "network unavailable",
    );

    expect(harness.state.realtime.locationCodes.value).toEqual(["custom-code"]);
    workflow.dispose();
  });

  test("refreshes history once when polling observes analysis completion", async () => {
    const harness = createHarness();
    harness.state.realtime.loggingStatus.value = {
      ...harness.state.realtime.loggingStatus.value,
      analysis_in_progress: true,
      last_completed_run_id: null,
    };
    const completedStatus: LoggingStatusPayload = {
      ...harness.state.realtime.loggingStatus.value,
      analysis_in_progress: false,
      last_completed_run_id: "run-42",
    };
    const responses = [completedStatus, completedStatus];
    api.getLoggingStatus.mockImplementation(async () => {
      const next = responses.shift();
      if (!next) {
        throw new Error("unexpected extra status request");
      }
      return next;
    });
    const workflow = createFeature(harness);

    await workflow.refreshLoggingStatus();
    await workflow.refreshLoggingStatus();

    expect(harness.state.realtime.loggingStatus.value).toEqual(completedStatus);
    expect(harness.recordingCalls).toEqual(["onRecordingStatusChanged"]);
    expect(workflow.signals.loggingError.value).toBeNull();
    workflow.dispose();
  });

  test("removes the selected client and emits a new selection without DOM fixtures", async () => {
    const harness = createHarness();
    harness.state.realtime.clients.value = [
      makeClient("client-a", { connected: true }),
      makeClient("client-b", { connected: true }),
    ];
    harness.state.realtime.selectedClientId.value = "client-a";
    api.removeClient.mockImplementation(async (clientId: string) => {
      harness.apiCalls.push(`removeClient:${clientId}`);
    });
    const workflow = createFeature(harness);

    await workflow.removeClient("client-a");

    expect(harness.confirmMessages).toEqual([
      "actions.remove_client_confirm:client-a",
    ]);
    expect(harness.apiCalls).toEqual(["removeClient:client-a"]);
    expect(
      harness.state.realtime.clients.value.map((client) => client.id),
    ).toEqual(["client-b"]);
    expect(harness.state.realtime.selectedClientId.value).toBe("client-b");
    expect(harness.selectionCalls).toEqual(["sendSelection"]);
    workflow.dispose();
  });

  test("does not remove a client when confirmation is declined", async () => {
    const harness = createHarness();
    harness.confirmResult = false;
    harness.state.realtime.clients.value = [
      makeClient("client-a", { connected: true }),
      makeClient("client-b", { connected: true }),
    ];
    harness.state.realtime.selectedClientId.value = "client-a";
    api.removeClient.mockImplementation(async (clientId: string) => {
      harness.apiCalls.push(`removeClient:${clientId}`);
    });
    const workflow = createFeature(harness);

    await workflow.removeClient("client-a");

    expect(harness.confirmMessages).toEqual([
      "actions.remove_client_confirm:client-a",
    ]);
    expect(harness.apiCalls).toEqual([]);
    expect(
      harness.state.realtime.clients.value.map((client) => client.id),
    ).toEqual(["client-a", "client-b"]);
    expect(harness.state.realtime.selectedClientId.value).toBe("client-a");
    expect(harness.selectionCalls).toEqual([]);
    workflow.dispose();
  });
});
