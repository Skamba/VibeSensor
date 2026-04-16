import { expect, test } from "@playwright/test";

import {
  createRealtimeFeatureWorkflow,
  createRealtimeFeatureWorkflowState,
} from "../src/app/features/realtime_feature_workflow";
import { createAppState } from "../src/app/ui_app_state";
import { signal, effect } from "../src/app/ui_signals";
import { defaultLocationCodes } from "../src/constants";
import type {
  ClientLocationsResponse,
  LoggingStatusPayload,
} from "../src/transport/http_models";
import type { AdaptedClient } from "../src/transport/live_models";

type WorkflowHarness = {
  state: ReturnType<typeof createAppState>;
  apiCalls: string[];
  selectionCalls: string[];
  recordingCalls: string[];
  confirmMessages: string[];
  pollerCalls: string[];
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
    pollerCalls: [],
    showErrors: [],
  };
}

test.describe("createRealtimeFeatureWorkflow", () => {
  test("starts logging through signal-backed workflow state and restarts polling", async () => {
    const harness = createHarness();
    harness.state.realtime.loggingStatus = {
      ...harness.state.realtime.loggingStatus,
      last_completed_run_id: "previous-run",
    };
    const nextStatus: LoggingStatusPayload = {
      ...harness.state.realtime.loggingStatus,
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
        async startLoggingRun() {
          harness.apiCalls.push("startLoggingRun");
          return nextStatus;
        },
      },
      createPollingController: () => ({
        start() {
          harness.pollerCalls.push("start");
        },
        stop() {
          harness.pollerCalls.push("stop");
        },
        restart() {
          harness.pollerCalls.push("restart");
        },
      }),
    });

    workflow.bindHandlers();
    await workflow.startLogging();

    expect(harness.pollerCalls).toEqual(["start", "restart"]);
    expect(harness.recordingCalls).toEqual(["onRecordingStatusChanged"]);
    expect(harness.apiCalls).toEqual(["startLoggingRun"]);
    expect(pendingTransitions).toEqual([null, "starting", null]);
    expect(workflow.signals.handlersBound.value).toBe(true);
    expect(workflow.signals.loggingError.value).toBeNull();
    expect(harness.state.realtime.loggingStatus).toEqual(nextStatus);
  });

  test("refreshes idle capture readiness from the signature signal instead of view render calls", async () => {
    const harness = createHarness();
    const idleCaptureReadinessSignature = signal("car-1##client-a");
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
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
          return harness.state.realtime.loggingStatus;
        },
      },
      createPollingController: () => ({
        start() {
          harness.pollerCalls.push("start");
        },
        stop() {
          harness.pollerCalls.push("stop");
        },
        restart() {
          harness.pollerCalls.push("restart");
        },
      }),
    });

    workflow.bindHandlers();

    await expect.poll(() => harness.apiCalls.length).toBe(1);
    idleCaptureReadinessSignature.value = "car-1##client-a|client-b";
    await expect.poll(() => harness.apiCalls.length).toBe(2);
    expect(harness.apiCalls).toEqual([
      "getLoggingStatus:car-1##client-a",
      "getLoggingStatus:car-1##client-a|client-b",
    ]);
  });

  test("falls back to default location codes when refreshing locations fails", async () => {
    const harness = createHarness();
    harness.state.realtime.locationCodes = ["custom-code"];
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
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

    await workflow.refreshLocationOptions();

    expect(harness.state.realtime.locationCodes).toEqual(defaultLocationCodes);
  });

  test("refreshes history once when polling observes analysis completion", async () => {
    const harness = createHarness();
    harness.state.realtime.loggingStatus = {
      ...harness.state.realtime.loggingStatus,
      analysis_in_progress: true,
      last_completed_run_id: null,
    };
    const completedStatus: LoggingStatusPayload = {
      ...harness.state.realtime.loggingStatus,
      analysis_in_progress: false,
      last_completed_run_id: "run-42",
    };
    const responses = [completedStatus, completedStatus];
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
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

    expect(harness.state.realtime.loggingStatus).toEqual(completedStatus);
    expect(harness.recordingCalls).toEqual(["onRecordingStatusChanged"]);
    expect(workflow.signals.loggingError.value).toBeNull();
  });

  test("removes the selected client and emits a new selection without DOM fixtures", async () => {
    const harness = createHarness();
    harness.state.realtime.clients = [
      makeClient("client-a", { connected: true }),
      makeClient("client-b", { connected: true }),
    ];
    harness.state.realtime.selectedClientId = "client-a";
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
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
    expect(harness.state.realtime.clients.map((client) => client.id)).toEqual(["client-b"]);
    expect(harness.state.realtime.selectedClientId).toBe("client-b");
    expect(harness.selectionCalls).toEqual(["sendSelection"]);
  });

  test("does not remove a client when confirmation is declined", async () => {
    const harness = createHarness();
    harness.state.realtime.clients = [
      makeClient("client-a", { connected: true }),
      makeClient("client-b", { connected: true }),
    ];
    harness.state.realtime.selectedClientId = "client-a";
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
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
    expect(harness.state.realtime.clients.map((client) => client.id)).toEqual([
      "client-a",
      "client-b",
    ]);
    expect(harness.state.realtime.selectedClientId).toBe("client-a");
    expect(harness.selectionCalls).toEqual([]);
  });
});
