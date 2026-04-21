import { describe, expect, test } from "vitest";
import { createEspFlashFeatureWorkflow } from "../src/app/features/esp_flash_feature_workflow";
import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../src/api/types";
import { signal } from "../src/app/ui_signals";
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
});
