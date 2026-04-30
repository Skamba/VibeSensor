import { describe, expect, test } from "vitest";
import {
  buildUpdateCurrentStatusSectionModel,
  buildUpdateLogSectionModel,
} from "../src/app/views/update_status_builders";
import { buildUpdateJourneySectionModel } from "../src/app/views/update_journey_builder";
import type {
  HealthStatusPayload,
  UpdateStatusPayload,
} from "../src/api/types";
import { createHealthyUpdateStatus } from "./maintenance_payload_test_support";

function t(key: string, vars?: Record<string, unknown>): string {
  if (!vars || Object.keys(vars).length === 0) {
    return key;
  }
  return `${key}:${JSON.stringify(vars)}`;
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

const deps = {
  t,
  selectedTransport: "wifi" as const,
};

describe("update status view models", () => {
  test("keeps runtime asset verification visible for asset-related failures", () => {
    const model = buildUpdateCurrentStatusSectionModel(
      makeStatus({
        state: "failed",
        phase: "installing",
        issues: [
          {
            phase: "installing",
            message: "static assets hash mismatch",
            detail: "Packaged artifacts are stale",
          },
        ],
        runtime: {
          ...makeStatus().runtime,
          assets_verified: false,
        },
      }),
      makeHealth(),
      deps,
    );

    expect(
      model.rows.find(
        (row) => row.labelText === "settings.update.runtime_assets_check",
      ),
    ).toEqual({
      labelText: "settings.update.runtime_assets_check",
      valueText: "settings.update.runtime_assets_bad",
    });
  });

  test("builds journey stage models and recovery guidance for failures", () => {
    const model = buildUpdateJourneySectionModel(
      makeStatus({
        state: "failed",
        phase: "restoring_hotspot",
        issues: [
          {
            phase: "restoring_hotspot",
            message: "Hotspot restart timed out",
            detail: "NetworkManager is still reconnecting to the uplink.",
          },
        ],
      }),
      deps,
    );

    expect(model.failureNote).toEqual({
      summaryText: "restoring_hotspot — Hotspot restart timed out",
      detailText: "NetworkManager is still reconnecting to the uplink.",
      recoveryTitleText: "settings.update.recovery.wifi.title",
      recoveryDetailText: "settings.update.recovery.wifi.detail",
    });
    expect(
      model.stages.find((stage) => stage.phase === "restoring_hotspot"),
    ).toMatchObject({
      state: "attention",
      current: false,
    });
  });

  test("marks the running stage current for usb-internet journeys", () => {
    const model = buildUpdateJourneySectionModel(
      makeStatus({
        state: "running",
        phase: "downloading",
        transport: "usb_internet",
      }),
      {
        ...deps,
        selectedTransport: "usb_internet",
      },
    );

    expect(
      model.stages.find((stage) => stage.phase === "connecting_usb_internet"),
    ).toMatchObject({
      state: "done",
      current: false,
    });
    expect(
      model.stages.find((stage) => stage.phase === "downloading"),
    ).toMatchObject({
      state: "active",
      current: true,
    });
  });

  test("builds the running empty-log state without forcing a log note", () => {
    const model = buildUpdateLogSectionModel(
      makeStatus({
        state: "running",
        log_tail: [],
      }),
      deps,
    );

    expect(model.subtitleText).toBe("settings.update.log_intro_running");
    expect(model.noteText).toBeNull();
    expect(model.emptyState).toEqual({
      titleText: "settings.update.log_running_title",
      bodyText: "settings.update.log_running_body",
    });
  });
});
