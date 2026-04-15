import { expect, test } from "@playwright/test";

import {
  buildEspFlashPanelRenderModel,
  createEspFlashFeaturePresenter,
  type EspFlashFeatureRenderState,
} from "../src/app/views/esp_flash_feature_presenter";
import type { EspFlashPanelRenderModel } from "../src/app/views/esp_flash_panel";
import type {
  EspFlashHistoryAttemptPayload,
  EspFlashStatusPayload,
  EspSerialPortPayload,
} from "../src/transport/http_models";

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

function makeState(
  overrides: Partial<EspFlashFeatureRenderState> = {},
): EspFlashFeatureRenderState {
  return {
    attempts: [],
    availablePorts: [],
    lastJourneyPhase: null,
    logText: "",
    selectedPortValue: "__auto__",
    status: makeStatus(),
    ...overrides,
  };
}

test.describe("buildEspFlashPanelRenderModel", () => {
  test("builds ready idle models with rendered port options and empty states", () => {
    const model = buildEspFlashPanelRenderModel(
      makeState({
        availablePorts: [makePort()],
      }),
      { t: (key) => key },
    );

    expect(model.portOptions).toEqual([
      { labelText: "settings.esp_flash.auto_detect", value: "__auto__" },
      {
        labelText: "/dev/ttyUSB0 — USB UART",
        value: "/dev/ttyUSB0",
      },
    ]);
    expect(model.startButtonDisabled).toBe(false);
    expect(model.startSummary.summary).toBe(
      "settings.esp_flash.start_readiness.summary_ready",
    );
    expect(model.startSummary.items[0]).toMatchObject({
      detail: "settings.esp_flash.start_readiness.item.connection_ready",
      state: "ready",
    });
    expect(model.readiness.summaryText).toBe(
      "settings.esp_flash.readiness.summary.ready_ports",
    );
    expect(model.history.emptyState?.titleText).toBe(
      "settings.esp_flash.history_empty_title",
    );
    expect(model.log.emptyState?.titleText).toBe(
      "settings.esp_flash.logs_idle_title",
    );
    expect(model.statusBanner).toEqual({
      text: "settings.esp_flash.state.idle",
      variant: "muted",
    });
  });

  test("builds running models with disabled controls and an active journey stage", () => {
    const model = buildEspFlashPanelRenderModel(
      makeState({
        availablePorts: [makePort()],
        selectedPortValue: "/dev/ttyUSB0",
        status: makeStatus({
          auto_detect: false,
          phase: "flashing",
          selected_port: "/dev/ttyUSB0",
          state: "running",
        }),
      }),
      { t: (key) => key },
    );

    expect(model.startButtonHidden).toBe(true);
    expect(model.cancelButtonHidden).toBe(false);
    expect(model.portSelectDisabled).toBe(true);
    expect(model.refreshPortsDisabled).toBe(true);
    expect(model.readiness.rows).toContainEqual({
      labelText: "settings.esp_flash.readiness.current_step",
      valueText: "flashing",
    });
    expect(
      model.journey.stages.find((stage) => stage.phase === "flashing"),
    ).toMatchObject({
      current: true,
      state: "active",
    });
    expect(
      model.journey.stages.filter((stage) => stage.state === "done"),
    ).toHaveLength(3);
    expect(model.log.emptyState?.titleText).toBe(
      "settings.esp_flash.logs_running_title",
    );
  });

  test("builds failed recovery models with fallback history and failed log state", () => {
    const model = buildEspFlashPanelRenderModel(
      makeState({
        availablePorts: [makePort()],
        lastJourneyPhase: "flashing",
        selectedPortValue: "/dev/ttyUSB0",
        status: makeStatus({
          auto_detect: false,
          error: "serial port disconnected",
          exit_code: 2,
          finished_at: 2,
          phase: "failed",
          selected_port: "/dev/ttyUSB0",
          started_at: 1,
          state: "failed",
        }),
      }),
      { t: (key) => key },
    );

    expect(model.startButtonLabelText).toBe("settings.esp_flash.retry");
    expect(model.startSummary.title).toBe("settings.esp_flash.recovery.title");
    expect(model.startSummary.items).toContainEqual({
      detail: "flashing",
      label: "settings.esp_flash.recovery.item.failed_step",
      state: "attention",
    });
    expect(model.readiness.errorText).toBe("serial port disconnected");
    expect(model.journey.terminalNoteText).toBe(
      "settings.esp_flash.journey_terminal.failed",
    );
    expect(
      model.journey.stages.find((stage) => stage.phase === "flashing"),
    ).toMatchObject({
      current: false,
      state: "attention",
    });
    expect(model.log.emptyState?.titleText).toBe(
      "settings.esp_flash.logs_failed_title",
    );
    expect(model.history.emptyState).toBeNull();
    expect(model.history.attempts[0]).toMatchObject({
      errorText: "serial port disconnected",
      portText: "/dev/ttyUSB0",
    });
  });

  test("prefers API history entries over fallback attempt synthesis", () => {
    const model = buildEspFlashPanelRenderModel(
      makeState({
        attempts: [
          makeAttempt({
            error: "upload failed",
            selected_port: "/dev/ttyUSB1",
            state: "failed",
          }),
        ],
        availablePorts: [makePort()],
        status: makeStatus({
          error: "ignored status error",
          selected_port: "/dev/ttyUSB0",
          state: "failed",
        }),
      }),
      { t: (key) => key },
    );

    expect(model.history.attempts).toHaveLength(1);
    expect(model.history.attempts[0]).toMatchObject({
      errorText: "upload failed",
      portText: "/dev/ttyUSB1",
    });
  });
});

test.describe("createEspFlashFeaturePresenter", () => {
  test("renders log output without a DOM-backed panel view", () => {
    let latestModel: EspFlashPanelRenderModel | null = null;
    const presenter = createEspFlashFeaturePresenter({
      panel: {
        bindActions() {},
        setModel(model) {
          latestModel = model;
        },
      },
      t: (key) => key,
    });

    presenter.render(
      makeState({
        availablePorts: [makePort()],
        logText: "build ok\nflash ok\n",
        status: makeStatus({
          log_count: 2,
          phase: "flashing",
          state: "running",
        }),
      }),
    );

    expect(latestModel?.log.emptyState).toBeNull();
    expect(latestModel?.log.text).toContain("flash ok");
    expect(latestModel?.statusBanner.text).toBe("settings.esp_flash.state.running");
  });
});
