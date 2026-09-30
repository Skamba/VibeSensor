import { beforeEach, describe, expect, test, vi } from "vitest";
import type {
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";
import { createUpdateFeature } from "../src/app/features/update_feature";
import { effect, signal } from "../src/app/ui_signals";
import type { InternetPanelView } from "../src/app/views/internet_panel";
import {
  createDeferred,
  expectSingleInFlightOperation,
  flushAsyncWork,
} from "./async_test_helpers";
import { createHealthyUpdateStatus } from "./maintenance_payload_test_support";
import { createTestQueryClient } from "./query_client_test_support";

const api = vi.hoisted(() => ({
  cancelUpdate: vi.fn(),
  getHealthStatus: vi.fn(),
  getUpdateInternetStatus: vi.fn(),
  getUpdateStatus: vi.fn(),
  startUpdate: vi.fn(),
}));

vi.mock("../src/api/settings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../src/api/settings")>()),
  ...api,
}));

beforeEach(() => {
  vi.resetAllMocks();
});

type FeatureHarness = {
  errors: string[];
  viewCalls: string[];
};

function createHarness(): FeatureHarness {
  return {
    errors: [],
    viewCalls: [],
  };
}

/**
 * Builds the controller against fake panels (polling stays off because the
 * update tab is not visible). `viewCalls` records SSID focus requests and the
 * controller clearing the internet panel's password field.
 */
function createFeature(harness: FeatureHarness) {
  const internet: InternetPanelView = {
    actions: signal(null),
    model: signal(null),
    focusSsidInput(): void {
      harness.viewCalls.push("focusSsidInput");
    },
  };
  const feature = createUpdateFeature({
    panels: {
      internet,
      update: { actions: signal(null), model: signal(null) },
    },
    activeViewId: signal("dashboardView"),
    activeSettingsTabId: signal("updateTab"),
    queryClient: createTestQueryClient(),
    services: {
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
    },
  });
  feature.bindUpdateHandlers();
  internet.actions.value?.onPasswordInput("secret");
  let previousPassword = "secret";
  effect(() => {
    const password = internet.model.value?.value.passwordInputValue ?? "";
    if (previousPassword !== "" && password === "") {
      harness.viewCalls.push("clearPassword");
    }
    previousPassword = password;
  });
  return feature;
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
  return createHealthyUpdateStatus(overrides);
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

describe("createUpdateFeature", () => {
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
    api.getUpdateStatus.mockImplementation(async () => {
      return status;
    });
    api.getHealthStatus.mockImplementation(async () => {
      return health;
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return internet;
    });
    const workflow = createFeature(harness);

    await workflow.refreshStatus();

    const renderState = workflow.renderState.value;
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
    api.getHealthStatus.mockImplementation(async () => {
      return makeHealth();
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return makeInternet();
    });
    api.getUpdateStatus.mockImplementation(async () => {
      return runningStatus;
    });
    api.startUpdate.mockImplementation(async (payload: unknown) => {
      startPayload = payload;
    });
    const workflow = createFeature(harness);

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
    expect(workflow.renderState.value.updateStatus).toEqual(runningStatus);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("focuses the SSID input instead of calling the API when wifi start is blocked", async () => {
    const harness = createHarness();
    api.startUpdate.mockImplementation(async () => {
      throw new Error("should not be called");
    });
    const workflow = createFeature(harness);

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
    api.startUpdate.mockImplementation(async () => {
      throw new Error("should not be called");
    });
    const workflow = createFeature(harness);

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

  test("surfaces runtime-boundary failures instead of silently normalizing them", async () => {
    const harness = createHarness();
    api.getHealthStatus.mockImplementation(async () => {
      return makeHealth();
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return makeInternet();
    });
    api.getUpdateStatus.mockImplementation(async () => {
      throw new Error(
        'Invalid update status response: /state Expected one of ["idle","running","success","failed"]',
      );
    });
    const workflow = createFeature(harness);

    await expect(workflow.refreshStatus()).rejects.toThrow(
      /Invalid update status response: \/state/,
    );
    expect(harness.errors).toContain(
      'Invalid update status response: /state Expected one of ["idle","running","success","failed"]',
    );
    workflow.dispose();
  });

  test("ignores older refresh results when a newer status refresh finishes first", async () => {
    const harness = createHarness();
    const olderStatus = createDeferred<UpdateStatusPayload>();
    const newerStatus = createDeferred<UpdateStatusPayload>();
    const statusRequests = [olderStatus, newerStatus];
    api.getHealthStatus.mockImplementation(async () => {
      return makeHealth();
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return makeInternet();
    });
    api.getUpdateStatus.mockImplementation(async () => {
      const request = statusRequests.shift();
      if (!request) {
        throw new Error("unexpected status request");
      }
      return request.promise;
    });
    const workflow = createFeature(harness);

    const olderRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    const newerRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    newerStatus.resolve(makeStatus({ phase: "installing", state: "running" }));
    await newerRefresh;
    olderStatus.resolve(makeStatus({ phase: "idle", state: "idle" }));
    await olderRefresh;

    expect(workflow.renderState.value.updateState).toBe("running");
    expect(workflow.renderState.value.updateStatus?.phase).toBe("installing");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("does not clear password or show errors when start resolves after disposal", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    api.startUpdate.mockImplementation(async () => {
      return start.promise;
    });
    const workflow = createFeature(harness);

    const starting = workflow.startUpdate({
      canStart: true,
      password: "secret",
      ssid: "Workshop Wi-Fi",
      transport: "wifi",
      usbAvailable: false,
    });
    await flushAsyncWork();
    workflow.dispose();
    start.resolve({});
    await starting;

    expect(harness.viewCalls).toEqual([]);
    expect(harness.errors).toEqual([]);
  });

  test("ignores overlapping update start requests while one is in flight", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    let startCalls = 0;
    api.getHealthStatus.mockImplementation(async () => {
      return makeHealth();
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return makeInternet();
    });
    api.getUpdateStatus.mockImplementation(async () => {
      return makeStatus({ phase: "installing", state: "running" });
    });
    api.startUpdate.mockImplementation(async () => {
      startCalls += 1;
      return start.promise;
    });
    const workflow = createFeature(harness);
    const intent = {
      canStart: true,
      password: "secret",
      ssid: "Workshop Wi-Fi",
      transport: "wifi" as const,
      usbAvailable: false,
    };

    await expectSingleInFlightOperation({
      callCount: () => startCalls,
      resolve: start.resolve,
      start: () => workflow.startUpdate(intent),
      value: {},
    });

    expect(startCalls).toBe(1);
    expect(harness.viewCalls).toEqual(["clearPassword"]);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("refreshes status after a successful update cancel", async () => {
    const harness = createHarness();
    let statusRequests = 0;
    api.cancelUpdate.mockImplementation(async () => {});
    api.getHealthStatus.mockImplementation(async () => {
      return makeHealth();
    });
    api.getUpdateInternetStatus.mockImplementation(async () => {
      return makeInternet();
    });
    api.getUpdateStatus.mockImplementation(async () => {
      statusRequests += 1;
      return makeStatus();
    });
    const workflow = createFeature(harness);

    await workflow.cancelUpdate();

    expect(statusRequests).toBe(1);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });
});
