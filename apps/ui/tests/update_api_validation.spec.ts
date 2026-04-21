import { beforeEach, describe, expect, test } from "vitest";

import {
  getHealthStatus,
  getUpdateInternetStatus,
  getUpdateStatus,
} from "../src/api/settings";
import { installWindowGlobal } from "./async_test_helpers";
import { HttpResponse, http, uiTestUrl } from "./msw/http";
import { createUiMswTestServer } from "./msw/node";

const mswServer = createUiMswTestServer();

function makeUpdateStatusPayload() {
  return {
    state: "idle",
    phase: "idle",
    transport: "wifi",
    started_at: null,
    finished_at: null,
    last_success_at: null,
    phase_started_at: null,
    phase_elapsed_s: null,
    updated_at: null,
    ssid: null,
    uplink_interface: null,
    issues: [],
    log_tail: [],
    exit_code: null,
    runtime: {
      version: "1.2.3",
      commit: "abcdef1234567890",
      ui_source_hash: "ui-hash",
      static_assets_hash: "assets-hash",
      static_build_source_hash: "build-hash",
      static_build_commit: "build-commit",
      assets_verified: true,
      has_packaged_static: true,
    },
  };
}

function makeUsbInternetStatusPayload() {
  return {
    detected: true,
    usable: true,
    interface_name: "usb0",
    connection_name: "USB uplink",
    driver: "cdc_ether",
    ipv4_addresses: ["10.0.0.2"],
    gateway: "10.0.0.1",
    has_default_route: true,
    diagnostic: "USB internet is ready on usb0.",
  };
}

function makeHealthPayload() {
  return {
    status: "ok",
    startup_state: "ready",
    startup_phase: "idle",
    startup_error: null,
    startup_warnings: [],
    background_task_failures: {},
    db_corruption_detected: false,
    processing_state: "idle",
    processing_failures: 0,
    processing_failure_categories: {},
    processing_last_failure: null,
    sample_rate_mismatch_count: 0,
    frame_size_mismatch_count: 0,
    degradation_reasons: [],
    data_loss: {
      tracked_clients: 0,
      affected_clients: 0,
      frames_dropped: 0,
      buffer_overflow_drops: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    persistence: {
      write_error: null,
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      analysis_queue_max_depth: 0,
      analysis_active_run_id: null,
      analysis_started_at: null,
      analysis_elapsed_s: null,
      analysis_queue_oldest_age_s: null,
      analyzing_run_count: 0,
      analyzing_oldest_age_s: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
    },
    intake_stats: {
      total_ingested_samples: 0,
      total_compute_calls: 0,
      last_compute_duration_s: 0,
      last_compute_all_duration_s: 0,
      last_ingest_duration_s: 0,
    },
    tick_duration_s: 0,
    max_tick_duration_s: 0,
    tick_count: 0,
    db_last_write_duration_s: 0,
    db_max_write_duration_s: 0,
  };
}

describe("update HTTP runtime boundary validation", () => {
  beforeEach(() => {
    installWindowGlobal();
  });

  test("accepts a schema-valid update status response", async () => {
    mswServer.use(
      http.get(uiTestUrl("/api/update/status"), () => HttpResponse.json(makeUpdateStatusPayload())),
    );

    await expect(getUpdateStatus()).resolves.toMatchObject({
      state: "idle",
      transport: "wifi",
    });
  });

  test("rejects malformed update status payloads at the API boundary", async () => {
    mswServer.use(
      http.get(
        uiTestUrl("/api/update/status"),
        () => HttpResponse.json({ ...makeUpdateStatusPayload(), state: "checking" }),
      ),
    );

    await expect(getUpdateStatus()).rejects.toThrow(/Invalid update status response: \/state/);
  });

  test("rejects malformed health payloads at the API boundary", async () => {
    mswServer.use(
      http.get(
        uiTestUrl("/api/health"),
        () => HttpResponse.json({
          ...makeHealthPayload(),
          data_loss: {
            ...makeHealthPayload().data_loss,
            parse_errors: "bad",
          },
        }),
      ),
    );

    await expect(getHealthStatus()).rejects.toThrow(/Invalid health status response: \/data_loss\/parse_errors/);
  });

  test("rejects malformed USB internet payloads at the API boundary", async () => {
    mswServer.use(
      http.get(
        uiTestUrl("/api/update/internet-status"),
        () => HttpResponse.json({
          ...makeUsbInternetStatusPayload(),
          ipv4_addresses: ["10.0.0.2", 42],
        }),
      ),
    );

    await expect(getUpdateInternetStatus()).rejects.toThrow(/Invalid USB internet status response: \/ipv4_addresses\/1/);
  });
});
