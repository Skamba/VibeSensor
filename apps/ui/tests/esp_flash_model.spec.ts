import { describe, expect, test } from "vitest";

import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../src/api/types";
import {
  AUTO_PORT,
  canStart,
  type FlashView,
  historyItems,
  journeyNote,
  journeyStages,
  logPlaceholder,
  nextJourneyPhase,
  readinessRows,
  readinessSummary,
  startLabel,
  startReadiness,
  statusBadge,
} from "../src/pages/esp_flash/esp_flash_model";

const t = (key: string) => key;

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

const PORT: EspSerialPortPayload = {
  description: "USB UART",
  pid: 2,
  port: "/dev/ttyUSB0",
  serial_number: "abc",
  vid: 1,
};

function makeView(overrides: Partial<FlashView> = {}): FlashView {
  return {
    attempts: [],
    ports: [],
    lastJourneyPhase: null,
    selectedPort: AUTO_PORT,
    status: makeStatus(),
    ...overrides,
  };
}

describe("esp flash model", () => {
  test("an idle board with a detected port is ready to flash", () => {
    const view = makeView({ ports: [PORT] });
    expect(canStart(view)).toBe(true);
    expect(startLabel(view, t)).toBe("settings.esp_flash.start");
    const readiness = startReadiness(view, t);
    expect(readiness.summary).toBe(
      "settings.esp_flash.start_readiness.summary_ready",
    );
    expect(readiness.items[0]).toMatchObject({
      detail: "settings.esp_flash.start_readiness.item.connection_ready",
      state: "ready",
    });
    expect(readinessSummary(view, t)).toBe(
      "settings.esp_flash.readiness.summary.ready_ports",
    );
    expect(historyItems(view, t)).toEqual([]);
    expect(logPlaceholder(view, "", t)?.title).toBe(
      "settings.esp_flash.logs_idle_title",
    );
    expect(statusBadge(view, t)).toEqual({
      text: "settings.esp_flash.state.idle",
      variant: "muted",
    });
  });

  test("without ports the start is blocked", () => {
    const view = makeView();
    expect(canStart(view)).toBe(false);
    expect(startReadiness(view, t)).toMatchObject({
      stateLabel: "maintenance.readiness.blocked",
      stateVariant: "bad",
    });
    expect(readinessSummary(view, t)).toBe(
      "settings.esp_flash.readiness.summary.ready_no_ports",
    );
  });

  test("a running flash shows the current step and an active stage", () => {
    const view = makeView({
      ports: [PORT],
      selectedPort: "/dev/ttyUSB0",
      status: makeStatus({
        auto_detect: false,
        phase: "flashing",
        selected_port: "/dev/ttyUSB0",
        state: "running",
      }),
    });
    expect(canStart(view)).toBe(false);
    expect(readinessRows(view, t)).toContainEqual({
      label: "settings.esp_flash.readiness.current_step",
      // Untranslated phases fall back to the raw phase name.
      value: "flashing",
    });
    const stages = journeyStages(view, t);
    expect(stages.find((stage) => stage.phase === "flashing")?.state).toBe(
      "active",
    );
    expect(stages.filter((stage) => stage.state === "done")).toHaveLength(3);
    expect(logPlaceholder(view, "", t)?.title).toBe(
      "settings.esp_flash.logs_running_title",
    );
    expect(logPlaceholder(view, "build ok\n", t)).toBeNull();
  });

  test("a failed flash offers recovery at the step that failed", () => {
    const view = makeView({
      ports: [PORT],
      lastJourneyPhase: "flashing",
      status: makeStatus({
        error: "serial port disconnected",
        exit_code: 2,
        finished_at: 2,
        phase: "failed",
        selected_port: "/dev/ttyUSB0",
        started_at: 1,
        state: "failed",
      }),
    });
    expect(startLabel(view, t)).toBe("settings.esp_flash.retry");
    const readiness = startReadiness(view, t);
    expect(readiness.title).toBe("settings.esp_flash.recovery.title");
    expect(readiness.items).toContainEqual({
      detail: "flashing",
      label: "settings.esp_flash.recovery.item.failed_step",
      state: "attention",
    });
    expect(readiness.items[2].detail).toBe(
      "settings.esp_flash.recovery.flashing.title — settings.esp_flash.recovery.flashing.detail",
    );
    expect(journeyNote(view, t)).toBe(
      "settings.esp_flash.journey_terminal.failed",
    );
    expect(
      journeyStages(view, t).find((stage) => stage.phase === "flashing")?.state,
    ).toBe("attention");
    expect(logPlaceholder(view, "", t)?.title).toBe(
      "settings.esp_flash.logs_failed_title",
    );
    // Without API history the failed status itself is the latest attempt.
    expect(historyItems(view, t)[0]).toMatchObject({
      error: "serial port disconnected",
      port: "/dev/ttyUSB0",
      variant: "bad",
    });
  });

  test("a cancelled flash without ports tells the user to reconnect", () => {
    const view = makeView({
      status: makeStatus({ phase: "cancelled", state: "cancelled" }),
    });
    const readiness = startReadiness(view, t);
    expect(readiness.summary).toBe(
      "settings.esp_flash.recovery.summary_blocked",
    );
    expect(readiness.items[2]).toMatchObject({
      detail: "settings.esp_flash.recovery.item.next_step_blocked",
      state: "blocked",
    });
  });

  test("API history wins over the synthesised status attempt", () => {
    const view = makeView({
      attempts: [
        makeAttempt({
          error: "upload failed",
          selected_port: "/dev/ttyUSB1",
          state: "failed",
        }),
      ],
      status: makeStatus({ error: "ignored", state: "failed" }),
    });
    expect(historyItems(view, t)).toEqual([
      expect.objectContaining({ error: "upload failed", port: "/dev/ttyUSB1" }),
    ]);
  });

  test("keeps the last journey phase when a later status only reports failure", () => {
    let phase = nextJourneyPhase(
      null,
      makeStatus({ phase: "erasing", state: "running" }),
    );
    expect(phase).toBe("erasing");
    phase = nextJourneyPhase(
      phase,
      makeStatus({ phase: "failed", state: "failed" }),
    );
    expect(phase).toBe("erasing");
    expect(
      nextJourneyPhase(phase, makeStatus({ phase: "idle", state: "idle" })),
    ).toBeNull();
  });
});
