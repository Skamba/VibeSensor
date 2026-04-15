import { expect, test } from "@playwright/test";

import {
  createRealtimeFeatureWorkflow,
  type RealtimeFeatureWorkflowViewPorts,
} from "../src/app/features/realtime_feature_workflow";
import { createAppState } from "../src/app/ui_app_state";
import { defaultLocationCodes } from "../src/constants";
import type {
  ClientLocationsResponse,
  LoggingStatusPayload,
} from "../src/transport/http_models";
import type { AdaptedClient } from "../src/transport/live_models";

type RenderLoggingState = {
  handlersBound: boolean;
  pendingLoggingAction: "starting" | "stopping" | null;
};

type WorkflowHarness = {
  state: ReturnType<typeof createAppState>;
  viewCalls: string[];
  renderStates: RenderLoggingState[];
  selectionCalls: string[];
  recordingCalls: string[];
  confirmMessages: string[];
  pollerCalls: string[];
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
    viewCalls: [],
    renderStates: [],
    selectionCalls: [],
    recordingCalls: [],
    confirmMessages: [],
    pollerCalls: [],
  };
}

function createViewPorts(harness: WorkflowHarness): RealtimeFeatureWorkflowViewPorts {
  return {
    maybeRenderSensorsSettingsList(force?: boolean): void {
      harness.viewCalls.push(`maybeRenderSensorsSettingsList:${String(force)}`);
    },
    renderStatus(clientRow?: AdaptedClient): void {
      harness.viewCalls.push(`renderStatus:${clientRow?.id ?? "none"}`);
    },
    renderLoggingStatus(state): void {
      harness.renderStates.push({
        handlersBound: state.handlersBound,
        pendingLoggingAction: state.pendingLoggingAction,
      });
      harness.viewCalls.push("renderLoggingStatus");
    },
    renderLoggingUnavailable(): void {
      harness.viewCalls.push("renderLoggingUnavailable");
    },
    renderLoggingError(message: string): void {
      harness.viewCalls.push(`renderLoggingError:${message}`);
    },
    getIdleCaptureReadinessSignature(): string {
      const clientIds = harness.state.realtime.clients.map((client) => client.id).join(",");
      return `${harness.state.settings.activeCarId ?? ""}##${clientIds}`;
    },
  };
}

test.describe("createRealtimeFeatureWorkflow", () => {
  test("starts logging through the workflow seam and restarts polling without DOM fixtures", async () => {
    const harness = createHarness();
    const nextStatus: LoggingStatusPayload = {
      ...harness.state.realtime.loggingStatus,
      enabled: true,
      run_id: "run-42",
      start_time_utc: "2026-04-05T09:00:00Z",
    };
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      t: (key) => key,
      showError: (message) => {
        harness.viewCalls.push(`showError:${message}`);
      },
      isDemoMode: false,
      view: createViewPorts(harness),
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
      confirmRemoveClient: () => true,
      api: {
        async startLoggingRun() {
          harness.viewCalls.push("api.startLoggingRun");
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
    expect(harness.renderStates).toEqual([
      { handlersBound: true, pendingLoggingAction: null },
      { handlersBound: true, pendingLoggingAction: "starting" },
      { handlersBound: true, pendingLoggingAction: null },
    ]);
    expect(harness.viewCalls).toContain("api.startLoggingRun");
    expect(harness.state.realtime.loggingStatus).toEqual(nextStatus);
  });

  test("falls back to default location codes when refreshing locations fails", async () => {
    const harness = createHarness();
    harness.state.realtime.locationCodes = ["custom-code"];
    const workflow = createRealtimeFeatureWorkflow({
      realtime: harness.state.realtime,
      t: (key) => key,
      showError: (message) => {
        harness.viewCalls.push(`showError:${message}`);
      },
      isDemoMode: false,
      view: createViewPorts(harness),
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
      confirmRemoveClient: () => true,
      api: {
        async getClientLocations(): Promise<ClientLocationsResponse> {
          throw new Error("network unavailable");
        },
      },
    });

    await workflow.refreshLocationOptions();

    expect(harness.state.realtime.locationCodes).toEqual(defaultLocationCodes);
    expect(harness.viewCalls).toEqual([
      "maybeRenderSensorsSettingsList:true",
      "renderStatus:none",
      "renderLoggingStatus",
    ]);
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
        harness.viewCalls.push(`showError:${message}`);
      },
      isDemoMode: false,
      view: createViewPorts(harness),
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
      confirmRemoveClient: () => true,
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
    expect(harness.viewCalls).toEqual(["renderLoggingStatus", "renderLoggingStatus"]);
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
        harness.viewCalls.push(`showError:${message}`);
      },
      isDemoMode: false,
      view: createViewPorts(harness),
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
      confirmRemoveClient: (message) => {
        harness.confirmMessages.push(message);
        return true;
      },
      api: {
        async removeClient(clientId: string) {
          harness.viewCalls.push(`api.removeClient:${clientId}`);
        },
      },
    });

    await workflow.removeClient("client-a");

    expect(harness.confirmMessages).toEqual(["actions.remove_client_confirm:client-a"]);
    expect(harness.state.realtime.clients.map((client) => client.id)).toEqual(["client-b"]);
    expect(harness.state.realtime.selectedClientId).toBe("client-b");
    expect(harness.selectionCalls).toEqual(["sendSelection"]);
    expect(harness.viewCalls).toEqual([
      "api.removeClient:client-a",
      "maybeRenderSensorsSettingsList:undefined",
      "renderLoggingStatus",
      "renderStatus:none",
    ]);
  });
});
