import { describe, expect, test } from "vitest";
import {
  createUpdateFeatureWorkflow,
  type UpdateFeatureWorkflowViewPorts,
} from "../src/app/features/update_feature_workflow";
import type {
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";
import { signal } from "../src/app/ui_signals";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  errors: string[];
  viewCalls: string[];
};

function createHarness(): WorkflowHarness {
  return {
    errors: [],
    viewCalls: [],
  };
}

function createViewPorts(
  harness: WorkflowHarness,
): UpdateFeatureWorkflowViewPorts {
  return {
    focusSsidInput(): void {
      harness.viewCalls.push("focusSsidInput");
    },
    clearPassword(): void {
      harness.viewCalls.push("clearPassword");
    },
  };
}

function makeStatus(
  overrides: Partial<UpdateStatusPayload> = {},
): UpdateStatusPayload {
  return {
    state: "idle",
    phase: "idle",
    transport: "wifi",
    ssid: null,
    uplink_interface: null,
    started_at: null,
    phase_started_at: null,
    phase_elapsed_s: null,
    finished_at: null,
    last_success_at: null,
    updated_at: null,
    issues: [],
    log_tail: [],
    exit_code: null,
    runtime: {
      version: "1.2.3",
      commit: "abcdef1234567890",
      ui_source_hash: "ui-hash",
      static_assets_hash: "feedfacecafebeef",
      static_build_source_hash: "build-hash",
      static_build_commit: "build-commit",
      assets_verified: true,
      has_packaged_static: true,
    },
    ...overrides,
  };
}

function makeHealth(
  overrides: Partial<HealthStatusPayload> = {},
): HealthStatusPayload {
  return {
    status: "ok",
    processing_state: "idle",
    processing_failures: 0,
    degradation_reasons: [],
    data_loss: {
      affected_clients: 0,
      tracked_clients: 0,
      frames_dropped: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    persistence: {
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      write_error: null,
      analysis_active_run_id: null,
      analysis_started_at: null,
      analysis_elapsed_s: null,
    },
    ...overrides,
  };
}

function makeInternet(
  overrides: Partial<UsbInternetStatusPayload> = {},
): UsbInternetStatusPayload {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: "settings.internet.load_failed",
    ...overrides,
  };
}

describe("createUpdateFeatureWorkflow", () => {
  test("refreshes update status through a no-DOM workflow seam", async () => {
    const harness = createHarness();
    const status = makeStatus({
      state: "running",
      phase: "installing",
      transport: "usb_internet",
      uplink_interface: "usb0",
    });
    const health = makeHealth();
    const internet = makeInternet({
      detected: true,
      usable: true,
      interface_name: "usb0",
      diagnostic: "USB internet is ready on usb0.",
    });
    const workflow = createUpdateFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      view: createViewPorts(harness),
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getUpdateStatus() {
          return status;
        },
        async getHealthStatus() {
          return health;
        },
        async getUpdateInternetStatus() {
          return internet;
        },
      },
    });

    await workflow.refreshStatus();

    const renderState = workflow.getRenderState();
    expect(renderState).toMatchObject({
      updateState: "running",
      updateTransport: "usb_internet",
      updateStatus: status,
      healthStatus: health,
    });
    expect(renderState.internetStatus).toMatchObject({
      usable: true,
      interface_name: "usb0",
    });
    workflow.dispose();
  });

  test("starts an update without DOM fixtures and refreshes status after a successful request", async () => {
    const harness = createHarness();
    let startPayload: unknown = null;
    const runningStatus = makeStatus({
      phase: "installing",
      state: "running",
      transport: "wifi",
    });
    const workflow = createUpdateFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      view: createViewPorts(harness),
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getHealthStatus() {
          return makeHealth();
        },
        async getUpdateInternetStatus() {
          return makeInternet();
        },
        async getUpdateStatus() {
          return runningStatus;
        },
        async startUpdate(payload) {
          startPayload = payload;
        },
      },
    });

    await workflow.startUpdate({
      canStart: true,
      password: "secret",
      ssid: "Workshop Wi-Fi",
      transport: "wifi",
      usbAvailable: false,
    });

    expect(startPayload).toEqual({
      transport: "wifi",
      ssid: "Workshop Wi-Fi",
      password: "secret",
    });
    expect(harness.viewCalls).toContain("clearPassword");
    expect(workflow.getRenderState().updateStatus).toEqual(runningStatus);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("focuses the SSID input instead of calling the API when wifi start is blocked", async () => {
    const harness = createHarness();
    const workflow = createUpdateFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      view: createViewPorts(harness),
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async startUpdate() {
          throw new Error("should not be called");
        },
      },
    });

    await workflow.startUpdate({
      canStart: false,
      password: "",
      ssid: "",
      transport: "wifi",
      usbAvailable: false,
    });

    expect(harness.viewCalls).toEqual(["focusSsidInput"]);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("still validates wifi inputs when a recovery retry bypasses readiness blocking", async () => {
    const harness = createHarness();
    const workflow = createUpdateFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      view: createViewPorts(harness),
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async startUpdate() {
          throw new Error("should not be called");
        },
      },
    });

    await workflow.startUpdate({
      canStart: true,
      password: "",
      ssid: "",
      transport: "wifi",
      usbAvailable: false,
    });

    expect(harness.viewCalls).toEqual(["focusSsidInput"]);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });
});
