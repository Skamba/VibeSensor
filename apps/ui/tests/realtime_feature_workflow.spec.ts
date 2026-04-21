import { describe, expect, test } from "vitest";
import {
  createRealtimeFeatureWorkflow,
  createRealtimeFeatureWorkflowState,
} from "../src/app/features/realtime_feature_workflow";
import { createAppState } from "../src/app/ui_app_state";
import { signal, effect } from "../src/app/ui_signals";
import type {
  ClientLocationsResponse,
  LoggingStatusPayload,
} from "../src/api/types";
import type { AdaptedClient } from "../src/transport/live_models";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  state: ReturnType<typeof createAppState>;
  apiCalls: string[];
  selectionCalls: string[];
  recordingCalls: string[];
  confirmMessages: string[];
  showErrors: string[];
};

function makeClient(id: string, overrides: Partial<AdaptedClient> = {}): AdaptedClient {
  return {
    id,
    name: id,
    connected: true,
    sample_rate_hz: 1000,
    frame_samples: 200,
    dropped_frames: 0,
    frames_total: 100,
    last_seen_age_ms: 10,
    ...overrides,
  };
}

function createHarness(): WorkflowHarness {
  return {
    state: createAppState(),
    apiCalls: [],
    selectionCalls: [],
    recordingCalls: [],
    confirmMessages: [],
    showErrors: [],
  };
}

describe("createRealtimeFeatureWorkflow", () => {
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
    const workflowState = createRealtimeFeatureWorkflowState();
    const pendingTransitions: Array<"starting" | "stopping" | null> = [];
    effect(() => {
      pendingTransitions.push(workflowState.pendingLoggingAction.value);
    });
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key) => key,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature: signal("previous-run"),
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async () => true,
      state: workflowState,
      api: {
        async getLoggingStatus() {
          harness.apiCalls.push("getLoggingStatus");
          return harness.state.realtime.loggingStatus.value;
        },
        async startLoggingRun() {
          harness.apiCalls.push("startLoggingRun");
          return nextStatus;
        },
      },
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

  test("refreshes idle capture readiness from the signature signal instead of view render calls", async () => {
    const harness = createHarness();
    const idleCaptureReadinessSignature = signal("car-1##client-a");
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key) => key,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature,
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async () => true,
      api: {
        async getLoggingStatus() {
          harness.apiCalls.push(`getLoggingStatus:${idleCaptureReadinessSignature.value}`);
          return harness.state.realtime.loggingStatus.value;
        },
      },
    });

    workflow.bindHandlers();

    await expect.poll(() => harness.apiCalls.length).toBeGreaterThanOrEqual(1);
    const initialCalls = harness.apiCalls.length;
    idleCaptureReadinessSignature.value = "car-1##client-a|client-b";
    await expect.poll(() => harness.apiCalls.length).toBeGreaterThan(initialCalls);
    expect(harness.apiCalls.at(-1)).toBe("getLoggingStatus:car-1##client-a|client-b");
    workflow.dispose();
  });

test("keeps the last known location codes and rejects when refreshing locations fails", async () => {
    const harness = createHarness();
    harness.state.realtime.locationCodes.value = ["custom-code"];
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key) => key,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature: signal("car-1##client-a"),
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async () => true,
      api: {
        async getClientLocations(): Promise<ClientLocationsResponse> {
          throw new Error("network unavailable");
        },
      },
    });

    await expect(workflow.refreshLocationOptions()).rejects.toThrow("network unavailable");

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
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key) => key,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature: signal("car-1##client-a"),
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async () => true,
      api: {
        async getLoggingStatus(): Promise<LoggingStatusPayload> {
          const next = responses.shift();
          if (!next) {
            throw new Error("unexpected extra status request");
          }
          return next;
        },
      },
    });

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
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key, vars) => `${key}:${String(vars?.id ?? "")}`,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature: signal("car-1##client-a|client-b"),
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async (message) => {
        harness.confirmMessages.push(message);
        return true;
      },
      api: {
        async removeClient(clientId: string) {
          harness.apiCalls.push(`removeClient:${clientId}`);
        },
      },
    });

    await workflow.removeClient("client-a");

    expect(harness.confirmMessages).toEqual(["actions.remove_client_confirm:client-a"]);
    expect(harness.apiCalls).toEqual(["removeClient:client-a"]);
    expect(harness.state.realtime.clients.value.map((client) => client.id)).toEqual(["client-b"]);
    expect(harness.state.realtime.selectedClientId.value).toBe("client-b");
    expect(harness.selectionCalls).toEqual(["sendSelection"]);
    workflow.dispose();
  });

  test("does not remove a client when confirmation is declined", async () => {
    const harness = createHarness();
    harness.state.realtime.clients.value = [
      makeClient("client-a", { connected: true }),
      makeClient("client-b", { connected: true }),
    ];
    harness.state.realtime.selectedClientId.value = "client-a";
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      queryClient: createTestQueryClient(),
      t: (key, vars) => `${key}:${String(vars?.id ?? "")}`,
      showError: (message) => {
        harness.showErrors.push(message);
      },
      isDemoMode: false,
      idleCaptureReadinessSignature: signal("car-1##client-a|client-b"),
      selection: {
        sendSelection() {
          harness.selectionCalls.push("sendSelection");
        },
      },
      recording: {
        async onRecordingStatusChanged() {
          harness.recordingCalls.push("onRecordingStatusChanged");
        },
      },
      confirmRemoveClient: async (message) => {
        harness.confirmMessages.push(message);
        return false;
      },
      api: {
        async removeClient(clientId: string) {
          harness.apiCalls.push(`removeClient:${clientId}`);
        },
      },
    });

    await workflow.removeClient("client-a");

    expect(harness.confirmMessages).toEqual(["actions.remove_client_confirm:client-a"]);
    expect(harness.apiCalls).toEqual([]);
    expect(harness.state.realtime.clients.value.map((client) => client.id)).toEqual([
      "client-a",
      "client-b",
    ]);
    expect(harness.state.realtime.selectedClientId.value).toBe("client-a");
    expect(harness.selectionCalls).toEqual([]);
    workflow.dispose();
  });
});
