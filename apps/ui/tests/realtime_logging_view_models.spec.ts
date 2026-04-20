import { describe, expect, test } from "vitest";
import {
  buildRealtimeCaptureReadinessChecklistModel,
  buildRealtimeLoggingPanelViewModel,
  captureReadinessSummaryText,
  type CaptureReadinessPayload,
} from "../src/app/views/realtime_logging_view_models";
import type { LoggingStatusPayload } from "../src/api/types";

function t(key: string, vars?: Record<string, unknown>): string {
  if (!vars || Object.keys(vars).length === 0) {
    return key;
  }
  return `${key}:${JSON.stringify(vars)}`;
}

function formatInt(value: number): string {
  return String(value);
}

function makeStatus(
  overrides: Partial<LoggingStatusPayload> = {},
): LoggingStatusPayload {
  return {
    enabled: false,
    run_id: null,
    write_error: null,
    analysis_in_progress: false,
    start_time_utc: null,
    samples_written: 0,
    samples_dropped: 0,
    last_completed_run_id: null,
    last_completed_run_error: null,
    capture_readiness: null,
    ...overrides,
  };
}

function makeCaptureReadiness(
  overrides: Partial<CaptureReadinessPayload> = {},
): CaptureReadinessPayload {
  return {
    is_ready: false,
    checks: [
      {
        check_key: "sensors_ready",
        state: "pass",
        reason_key: "ready",
        details: {
          live_sensor_count: 4,
        },
      },
      {
        check_key: "reference_ready",
        state: "fail",
        reason_key: "speed_source_missing",
        details: {},
      },
      {
        check_key: "speed_stable",
        state: "fail",
        reason_key: "speed_sample_missing",
        details: {},
      },
      {
        check_key: "capture_ready",
        state: "fail",
        reason_key: "capture_blocked",
        details: {},
      },
    ],
    ...overrides,
  };
}

describe("realtime logging view models", () => {
  test("builds the no-cars blocked panel as typed model data", () => {
    const model = buildRealtimeLoggingPanelViewModel({
      status: makeStatus(),
      pendingLoggingAction: null,
      selectionBlockReason: "no_cars",
      liveHealth: {
        variant: "warn",
        text: "dashboard.health.attention",
        summary: "dashboard.logging.active_car_required",
        showOverviewPill: true,
      },
      connectedCountText: "1",
      assignedCountText: "0",
      runIdText: "",
      elapsedText: "--",
      samplesText: "0",
      lastCompletedElapsedText: "--",
      t,
      formatInt,
    });

    expect(model.summaryPanel).toEqual({
      titleText: "dashboard.logging.blocked.no_cars.title",
      bodyText: "dashboard.logging.blocked.no_cars.body",
      detailText: "dashboard.logging.blocked.no_cars.detail",
      action: {
        action: "open-add-car",
        labelText: "dashboard.logging.blocked.no_cars.action",
        variant: "success",
      },
    });
    expect(model.checklist).toBeNull();
    expect(model.summaryAction?.action).toBe("open-add-car");
    expect(model.summaryHidden).toBe(false);
    expect(model.shellLayout).toBe("setup");
    expect(model.showProgressSection).toBe(false);
    expect(model.setupMode).toBe(true);
    expect(model.startDisabled).toBe(true);
  });

  test("builds setup summary and checklist view models for readiness failures", () => {
    const captureReadiness = makeCaptureReadiness();
    const model = buildRealtimeLoggingPanelViewModel({
      status: makeStatus({
        capture_readiness: captureReadiness,
      }),
      pendingLoggingAction: null,
      selectionBlockReason: null,
      liveHealth: {
        variant: "warn",
        text: "dashboard.health.attention",
        summary: "dashboard.capture_readiness.reference_ready.speed_source_missing",
        showOverviewPill: true,
      },
      connectedCountText: "4",
      assignedCountText: "4",
      runIdText: "",
      elapsedText: "--",
      samplesText: "0",
      lastCompletedElapsedText: "--",
      t,
      formatInt,
    });

    expect(captureReadinessSummaryText(captureReadiness, { t, formatInt }))
      .toBe("dashboard.capture_readiness.reference_ready.speed_source_missing");
    expect(model.summaryPanel).toEqual({
      titleText: "dashboard.logging.blocked.setup.title",
      bodyText: "dashboard.capture_readiness.reference_ready.speed_source_missing",
      action: {
        action: "open-speed-source",
        labelText: "dashboard.logging.blocked.setup.action.speed_source",
      },
    });
    expect(model.checklist).toEqual(buildRealtimeCaptureReadinessChecklistModel(captureReadiness, {
      setupMode: true,
      t,
      formatInt,
    }));
    expect(model.checklist?.items.map((item) => item.checkKey)).toEqual([
      "reference_ready",
      "speed_stable",
    ]);
    expect(model.summaryLayout).toBe("panel");
    expect(model.checklistHidden).toBe(false);
    expect(model.showProgressSection).toBe(true);
  });

  test("preserves the last completed elapsed value when processing begins", () => {
    const model = buildRealtimeLoggingPanelViewModel({
      status: makeStatus({
        analysis_in_progress: true,
        last_completed_run_id: "run-9",
      }),
      pendingLoggingAction: null,
      selectionBlockReason: null,
      liveHealth: {
        variant: "ok",
        text: "dashboard.health.ready",
        summary: "",
        showOverviewPill: false,
      },
      connectedCountText: "4",
      assignedCountText: "4",
      runIdText: "dashboard.logging.last_run_id:{\"runId\":\"run-9\"}",
      elapsedText: "--",
      samplesText: "1200",
      lastCompletedElapsedText: "1:23",
      t,
      formatInt,
    });

    expect(model.elapsedText).toBe("1:23");
    expect(model.summaryPanel).toEqual({
      titleText: "dashboard.logging.processing.title:{\"runId\":\"run-9\"}",
      bodyText: "dashboard.logging.processing.body",
      detailText: "dashboard.logging.processing.detail",
      action: {
        action: "open-history",
        labelText: "dashboard.logging.processing.action",
      },
    });
    expect(model.nextLastCompletedElapsedText).toBe("1:23");
    expect(model.loggingRowHidden).toBe(false);
    expect(model.pillHidden).toBe(true);
    expect(model.runIdHidden).toBe(false);
  });
});
