import { describe, expect, test } from "vitest";
import { createEspFlashFeatureWorkflow } from "../src/app/features/esp_flash_feature_workflow";
import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../src/api/types";
import { signal } from "../src/app/ui_signals";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import { createTestQueryClient } from "./query_client_test_support";

type WorkflowHarness = {
  errors: string[];
};

function createHarness(): WorkflowHarness {
  return {
    errors: [],
  };
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

describe("createEspFlashFeatureWorkflow", () => {
  test("refreshes flash status, logs, and history without DOM bindings", async () => {
    const harness = createHarness();
    const status = makeStatus({
      state: "running",
      phase: "flashing",
      selected_port: "/dev/ttyUSB0",
      log_count: 2,
    });
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashStatus() {
          return status;
        },
        async getEspFlashLogs() {
          return {
            from_index: 0,
            next_index: 2,
            lines: ["erase ok", "flash ok"],
          };
        },
        async getEspFlashHistory() {
          return {
            attempts: [makeAttempt()],
          };
        },
      },
    });

    await workflow.refreshStatus();

    const renderState = workflow.getRenderState();
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
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashStatus() {
          return status;
        },
        async getEspFlashLogs() {
          return {
            from_index: 0,
            next_index: 0,
            lines: [],
          };
        },
        async getEspFlashHistory() {
          return {
            attempts: [],
          };
        },
      },
    });

    await workflow.refreshStatus();
    status = makeStatus({
      state: "failed",
      phase: "failed",
      error: "serial port disconnected",
      selected_port: "/dev/ttyUSB0",
    });
    await workflow.refreshStatus();

    expect(workflow.getRenderState().lastJourneyPhase).toBe("flashing");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("starts flashing with the selected target and refreshes query-backed state", async () => {
    const harness = createHarness();
    let startArgs: { autoDetect: boolean; port: string | null } | null = null;
    let status = makeStatus({
      log_count: 2,
    });
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashPorts() {
          return {
            ports: [makePort()],
          };
        },
        async getEspFlashStatus() {
          return status;
        },
        async getEspFlashLogs() {
          return {
            from_index: 0,
            next_index: 2,
            lines: ["old log line"],
          };
        },
        async getEspFlashHistory() {
          return {
            attempts: [],
          };
        },
        async startEspFlash(port, autoDetect) {
          startArgs = { port, autoDetect };
          status = makeStatus({
            log_count: 0,
            phase: "validating",
            state: "running",
          });
        },
      },
    });

    await workflow.refreshPorts();
    workflow.setSelectedPortValue("/dev/ttyUSB0");
    await workflow.refreshStatus();
    await workflow.startFlash();

    expect(startArgs).toEqual({
      port: "/dev/ttyUSB0",
      autoDetect: false,
    });
    expect(workflow.getRenderState().logText).toBe("");
    expect(workflow.getRenderState().status.state).toBe("running");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores older status refresh results when a newer refresh finishes first", async () => {
    const harness = createHarness();
    const olderStatus = createDeferred<EspFlashStatusPayload>();
    const newerStatus = createDeferred<EspFlashStatusPayload>();
    const statusRequests = [olderStatus, newerStatus];
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashStatus() {
          const request = statusRequests.shift();
          if (!request) {
            throw new Error("unexpected status request");
          }
          return request.promise;
        },
        async getEspFlashHistory() {
          return { attempts: [] };
        },
      },
    });

    const olderRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    const newerRefresh = workflow.refreshStatus();
    await flushAsyncWork();
    newerStatus.resolve(makeStatus({ phase: "flashing", state: "running" }));
    await newerRefresh;
    olderStatus.resolve(makeStatus({ phase: "idle", state: "idle" }));
    await olderRefresh;

    expect(workflow.getRenderState().status.state).toBe("running");
    expect(workflow.getRenderState().lastJourneyPhase).toBe("flashing");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("does not update state or show errors when flash start resolves after disposal", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashPorts() {
          return { ports: [makePort()] };
        },
        async startEspFlash() {
          return start.promise;
        },
      },
    });

    await workflow.refreshPorts();
    const starting = workflow.startFlash();
    await flushAsyncWork();
    workflow.dispose();
    start.resolve({});
    await starting;

    expect(workflow.getRenderState().status.state).toBe("idle");
    expect(workflow.getRenderState().logText).toBe("");
    expect(harness.errors).toEqual([]);
  });

  test("ignores overlapping flash starts while one is in flight", async () => {
    const harness = createHarness();
    const start = createDeferred<unknown>();
    let startCalls = 0;
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async getEspFlashHistory() {
          return { attempts: [] };
        },
        async getEspFlashPorts() {
          return { ports: [makePort()] };
        },
        async getEspFlashStatus() {
          return makeStatus({ phase: "validating", state: "running" });
        },
        async startEspFlash() {
          startCalls += 1;
          return start.promise;
        },
      },
    });

    await workflow.refreshPorts();
    const firstStart = workflow.startFlash();
    void workflow.startFlash();
    await flushAsyncWork();
    start.resolve({});
    await firstStart;

    expect(startCalls).toBe(1);
    expect(workflow.getRenderState().status.state).toBe("running");
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });

  test("ignores overlapping flash cancels while one is in flight", async () => {
    const harness = createHarness();
    const cancel = createDeferred<unknown>();
    let cancelCalls = 0;
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async cancelEspFlash() {
          cancelCalls += 1;
          return cancel.promise;
        },
        async getEspFlashHistory() {
          return { attempts: [] };
        },
        async getEspFlashStatus() {
          return makeStatus();
        },
      },
    });

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
    const workflow = createEspFlashFeatureWorkflow({
      t: (key) => key,
      showError: (message) => {
        harness.errors.push(message);
      },
      pollingEnabled: signal(false),
      queryClient: createTestQueryClient(),
      api: {
        async cancelEspFlash() {},
        async getEspFlashHistory() {
          return { attempts: [] };
        },
        async getEspFlashStatus() {
          statusRequests += 1;
          return makeStatus();
        },
      },
    });

    await workflow.cancelFlash();

    expect(statusRequests).toBe(1);
    expect(harness.errors).toEqual([]);
    workflow.dispose();
  });
});
