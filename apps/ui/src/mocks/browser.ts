import { setupWorker } from "msw/browser";
import { HttpResponse, http } from "../../tests/msw/http";
import {
  buildHistoryDownloadHandlers,
  buildHistoryHandlers,
  makeHistoryListPayload,
  makeHistoryListRun,
} from "../../tests/msw/handlers/history";
import {
  buildAnalysisSettingsHandlers,
  buildCarLibraryHandlers,
  buildCarsHandlers,
  buildSpeedSourceHandlers,
  makeCarsPayload,
} from "../../tests/msw/handlers/settings";

type RecordingStatusPayload = {
  analysis_in_progress: boolean;
  capture_readiness: {
    checks: Array<{
      check_key: string;
      details: Record<string, unknown>;
      reason_key: string;
      state: "fail" | "pass" | "warn";
    }>;
    is_ready: boolean;
  };
  enabled: boolean;
  last_completed_run_error: string | null;
  last_completed_run_id: string | null;
  run_id: string | null;
  samples_dropped: number;
  samples_written: number;
  start_time_utc: string | null;
  write_error: string | null;
};

function makeRecordingStatusPayload(): RecordingStatusPayload {
  return {
    analysis_in_progress: false,
    capture_readiness: {
      is_ready: false,
      checks: [
        {
          check_key: "sensors_ready",
          details: {},
          reason_key: "no_live_sensors",
          state: "fail",
        },
        {
          check_key: "reference_ready",
          details: {},
          reason_key: "active_car_missing",
          state: "fail",
        },
        {
          check_key: "speed_stable",
          details: {},
          reason_key: "speed_sample_missing",
          state: "fail",
        },
        {
          check_key: "capture_ready",
          details: { blocking_check: "sensors_ready" },
          reason_key: "capture_blocked",
          state: "fail",
        },
      ],
    },
    enabled: false,
    last_completed_run_error: null,
    last_completed_run_id: null,
    run_id: null,
    samples_dropped: 0,
    samples_written: 0,
    start_time_utc: null,
    write_error: null,
  };
}

function makeUpdateStatusPayload() {
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
  };
}

function makeHealthStatusPayload() {
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
  };
}

function makeUsbInternetStatusPayload() {
  return {
    detected: false,
    usable: false,
    interface_name: null,
    connection_name: null,
    driver: null,
    ipv4_addresses: [],
    gateway: null,
    has_default_route: false,
    diagnostic: "No USB network interface is currently detected.",
  };
}

function makeEspFlashPortsPayload() {
  return {
    ports: [],
  };
}

function makeEspFlashStatusPayload() {
  return {
    state: "idle",
    phase: "idle",
    selected_port: null,
    auto_detect: true,
    last_success_at: null,
    error: null,
    log_count: 0,
    job_id: null,
    started_at: null,
    finished_at: null,
    exit_code: null,
  };
}

function makeEspFlashLogsPayload() {
  return {
    from_index: 0,
    next_index: 0,
    lines: [],
  };
}

function makeEspFlashHistoryPayload() {
  return {
    attempts: [],
  };
}

const historyList = makeHistoryListPayload({
  runs: [
    makeHistoryListRun("run-001", {
      car_name: "Mock Demo Car",
      sample_count: 128,
    }),
  ],
});

const mockWorker = setupWorker(
  http.get("/api/settings/language", () => HttpResponse.json({ language: "en" })),
  http.put("/api/settings/language", () => HttpResponse.json({ language: "en" })),
  http.get("/api/settings/speed-unit", () => HttpResponse.json({ speed_unit: "kmh" })),
  http.put("/api/settings/speed-unit", () => HttpResponse.json({ speed_unit: "kmh" })),
  http.get("/api/recording/status", () => HttpResponse.json(makeRecordingStatusPayload())),
  http.post("/api/recording/start", () => HttpResponse.json(makeRecordingStatusPayload())),
  http.post("/api/recording/stop", () => HttpResponse.json(makeRecordingStatusPayload())),
  http.get("/api/client-locations", () => HttpResponse.json({ locations: [] })),
  http.get("/api/update/status", () => HttpResponse.json(makeUpdateStatusPayload())),
  http.get("/api/health", () => HttpResponse.json(makeHealthStatusPayload())),
  http.get("/api/update/internet-status", () => HttpResponse.json(makeUsbInternetStatusPayload())),
  http.get("/api/esp-flash/ports", () => HttpResponse.json(makeEspFlashPortsPayload())),
  http.get("/api/esp-flash/status", () => HttpResponse.json(makeEspFlashStatusPayload())),
  http.get("/api/esp-flash/logs", () => HttpResponse.json(makeEspFlashLogsPayload())),
  http.get("/api/esp-flash/history", () => HttpResponse.json(makeEspFlashHistoryPayload())),
  ...buildAnalysisSettingsHandlers(),
  ...buildCarsHandlers({
    load: makeCarsPayload({
      cars: [],
      active_car_id: null,
    }),
  }),
  ...buildSpeedSourceHandlers(),
  ...buildCarLibraryHandlers(),
  ...buildHistoryHandlers({
    list: historyList,
  }),
  ...buildHistoryDownloadHandlers(),
);

export async function startBrowserMocksIfEnabled(): Promise<boolean> {
  const mockMode = import.meta.env.MODE === "msw"
    || import.meta.env.VITE_UI_MSW_MODE === "browser";
  if (!mockMode) {
    return false;
  }
  await mockWorker.start({
    onUnhandledRequest: "bypass",
    serviceWorker: {
      url: "/mockServiceWorker.js",
    },
  });
  return true;
}
