import { beforeEach, describe, expect, test, vi } from "vitest";
import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../src/api/types";
import { createEspFlashFeature } from "../src/app/features/esp_flash_feature";
import { signal } from "../src/app/ui_signals";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import { createTestQueryClient } from "./query_client_test_support";

const api = vi.hoisted(() => ({
  cancelEspFlash: vi.fn(),
  getEspFlashHistory: vi.fn(),
  getEspFlashLogs: vi.fn(),
  getEspFlashPorts: vi.fn(),
  getEspFlashStatus: vi.fn(),
  startEspFlash: vi.fn(),
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
};

function createHarness(): FeatureHarness {
  return {
    errors: [],
  };
}

/** Builds the controller against a fake panel with tab polling off. */
function createFeature(harness: FeatureHarness) {
  return createEspFlashFeature({
    panel: { actions: signal(null), model: signal(null) },
    activeViewId: signal("dashboardView"),
    activeSettingsTabId: signal("espFlashTab"),
    queryClient: createTestQueryClient(),
    services: {
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
    },
  });
}

function makeStatus(
  overrides: Partial<EspFlashStatusPayload> = {},
): EspFlashStatusPayload {
  return {
    auto_detect: true,
    error: null,
    exit_code: null,
    finished_at: null,
    job_id: 1,
    last_success_at: null,
    log_count: 0,
    phase: "idle",
    selected_port: null,
    started_at: null,
    state: "idle",
    ...overrides,
  };
}

function makeAttempt(
  overrides: Partial<EspFlashHistoryAttemptPayload> = {},
): EspFlashHistoryAttemptPayload {
  return {
    auto_detect: false,
    error: null,
    exit_code: 0,
    finished_at: 2,
    job_id: 1,
    selected_port: "/dev/ttyUSB0",
    started_at: 1,
    state: "success",
    ...overrides,
  };
}

function makePort(
  overrides: Partial<EspSerialPortPayload> = {},
): EspSerialPortPayload {
  return {
    description: "USB UART",
    pid: 2,
    port: "/dev/ttyUSB0",
    serial_number: "abc",
    vid: 1,
    ...overrides,
  };
}

describe("createEspFlashFeature", () => {
  test("refreshes flash status, logs, and history without DOM bindings", async () => {
    const harness = createHarness();
    const status = makeStatus({
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      log_count: 2,
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      return status;
    });
    api.getEspFlashLogs.mockImplementation(async () => {
      return {
        from_index: 0,
        next_index: 2,
        lines: ["erase ok", "flash ok"],
      };
    });
    api.getEspFlashHistory.mockImplementation(async () => {
      return {
        attempts: [makeAttempt()],
      };
    });
    const workflow = createFeature(harness);

    await workflow.refreshStatus();

    const renderState = workflow.renderState.value;
    expect(renderState).toMatchObject({
      status,
      lastJourneyPhase: "flashing",
    });
    expect(renderState.logText).toContain("erase ok");
    expect(renderState.attempts).toHaveLength(1);
    workflow.dispose();
  });

  test("keeps the last running journey phase when a later status only reports failure", async () => {
    const harness = createHarness();
    let status = makeStatus({
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      return status;
    });
    api.getEspFlashLogs.mockImplementation(async () => {
      return {
        from_index: 0,
        next_index: 0,
        lines: [],
      };
    });
    api.getEspFlashHistory.mockImplementation(async () => {
      return {
        attempts: [],
      };
    });
    const workflow = createFeature(harness);

    await workflow.refreshStatus();
    status = makeStatus({
      state: "failed",
      phase: "failed",
      error: "serial port disconnected",
      selected_port: "/dev/ttyUSB0",
    });
    await workflow.refreshStatus();

    expect(workflow.renderState.value.lastJourneyPhase).toBe("flashing");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("starts flashing with the selected target and refreshes query-backed state", async () => {
    const harness = createHarness();
    let startArgs: { autoDetect: boolean; port: string | null } | null = null;
    let status = makeStatus({
      log_count: 2,
    });
    api.getEspFlashPorts.mockImplementation(async () => {
      return {
        ports: [makePort()],
      };
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      return status;
    });
    api.getEspFlashLogs.mockImplementation(async () => {
      return {
        from_index: 0,
        next_index: 2,
        lines: ["old log line"],
      };
    });
    api.getEspFlashHistory.mockImplementation(async () => {
      return {
        attempts: [],
      };
    });
    api.startEspFlash.mockImplementation(async (port, autoDetect) => {
      startArgs = { port, autoDetect };
      status = makeStatus({
        log_count: 0,
        phase: "validating",
        state: "running",
      });
    });
    const workflow = createFeature(harness);

    await workflow.refreshPorts();
    workflow.setSelectedPortValue("/dev/ttyUSB0");
    await workflow.refreshStatus();
    await workflow.startFlash();

    expect(startArgs).toEqual({
      port: "/dev/ttyUSB0",
      autoDetect: false,
    });
    expect(workflow.renderState.value.logText).toBe("");
    expect(workflow.renderState.value.status.state).toBe("running");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores older status refresh results when a newer refresh finishes first", async () => {
    const harness = createHarness();
    const olderStatus = createDeferred<EspFlashStatusPayload>();
    const newerStatus = createDeferred<EspFlashStatusPayload>();
    const statusRequests = [olderStatus, newerStatus];
    api.getEspFlashStatus.mockImplementation(async () => {
      const request = statusRequests.shift();
      if (!request) {
        throw new Error("unexpected status request");
      }
      return request.promise;
    });
    api.getEspFlashHistory.mockImplementation(async () => {
      return { attempts: [] };
    });
    const workflow = createFeature(harness);

    const olderRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    const newerRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    newerStatus.resolve(makeStatus({ phase: "flashing", state: "running" }));
    await newerRefresh;
    olderStatus.resolve(makeStatus({ phase: "idle", state: "idle" }));
    await olderRefresh;

    expect(workflow.renderState.value.status.state).toBe("running");
    expect(workflow.renderState.value.lastJourneyPhase).toBe("flashing");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("does not update state or show errors when flash start resolves after disposal", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    api.getEspFlashPorts.mockImplementation(async () => {
      return { ports: [makePort()] };
    });
    api.startEspFlash.mockImplementation(async () => {
      return start.promise;
    });
    const workflow = createFeature(harness);

    await workflow.refreshPorts();
    const starting = workflow.startFlash();
    await flushAsyncWork();
    workflow.dispose();
    start.resolve({});
    await starting;

    expect(workflow.renderState.value.status.state).toBe("idle");
    expect(workflow.renderState.value.logText).toBe("");
    expect(harness.errors).toEqual([]);
  });

  test("ignores overlapping flash starts while one is in flight", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    let startCalls = 0;
    api.getEspFlashHistory.mockImplementation(async () => {
      return { attempts: [] };
    });
    api.getEspFlashPorts.mockImplementation(async () => {
      return { ports: [makePort()] };
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      return makeStatus({ phase: "validating", state: "running" });
    });
    api.startEspFlash.mockImplementation(async () => {
      startCalls += 1;
      return start.promise;
    });
    const workflow = createFeature(harness);

    await workflow.refreshPorts();
    const firstStart = workflow.startFlash();
    void workflow.startFlash();
    await flushAsyncWork();
    start.resolve({});
    await firstStart;

    expect(startCalls).toBe(1);
    expect(workflow.renderState.value.status.state).toBe("running");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores overlapping flash cancels while one is in flight", async () => {
    const harness = createHarness();
    const cancel = createDeferred<unknown>();
    let cancelCalls = 0;
    api.cancelEspFlash.mockImplementation(async () => {
      cancelCalls += 1;
      return cancel.promise;
    });
    api.getEspFlashHistory.mockImplementation(async () => {
      return { attempts: [] };
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      return makeStatus();
    });
    const workflow = createFeature(harness);

    const firstCancel = workflow.cancelFlash();
    void workflow.cancelFlash();
    await flushAsyncWork();
    cancel.resolve({});
    await firstCancel;

    expect(cancelCalls).toBe(1);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("refreshes status after a successful flash cancel", async () => {
    const harness = createHarness();
    let statusRequests = 0;
    api.cancelEspFlash.mockImplementation(async () => {});
    api.getEspFlashHistory.mockImplementation(async () => {
      return { attempts: [] };
    });
    api.getEspFlashStatus.mockImplementation(async () => {
      statusRequests += 1;
      return makeStatus();
    });
    const workflow = createFeature(harness);

    await workflow.cancelFlash();

    expect(statusRequests).toBe(1);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });
});
