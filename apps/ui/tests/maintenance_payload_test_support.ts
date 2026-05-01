import type {
  EspSerialPortPayload,
  HealthStatusPayload,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "../src/api/types";

export function createEspFlashPort(
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

export function createIdleUpdateStatus(
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

export function createHealthyUpdateStatus(
  overrides: Partial<HealthStatusPayload> = {},
): HealthStatusPayload {
  return {
    status: "ok",
    startup_state: "ready",
    startup_phase: "idle",
    startup_error: null,
    startup_warnings: [],
    background_task_failures: {},
    db_corruption_detected: false,
    db_engine_unhealthy: false,
    db_engine_unhealthy_details: null,
    db_engine_unhealthy_reason: null,
    db_last_write_duration_s: 0,
    db_max_write_duration_s: 0,
    processing_state: "idle",
    processing_failures: 0,
    processing_failure_categories: {},
    processing_last_failure: null,
    sample_rate_mismatch_count: 0,
    frame_size_mismatch_count: 0,
    degradation_reasons: [],
    subsystems: {
      database: { reason_codes: [], status: "ready" },
      firmware: { reason_codes: [], status: "ready" },
      hotspot_network: { reason_codes: [], status: "ready" },
      ingest: { reason_codes: [], status: "ready" },
      post_analysis: { reason_codes: [], status: "ready" },
      raw_capture: { reason_codes: [], status: "ready" },
      recorder: { reason_codes: [], status: "ready" },
      runtime: { reason_codes: [], status: "ready" },
      updates: { reason_codes: [], status: "ready" },
      websocket: { reason_codes: [], status: "ready" },
    },
    data_loss: {
      affected_clients: 0,
      buffer_overflow_drops: 0,
      tracked_clients: 0,
      frames_dropped: 0,
      queue_overflow_drops: 0,
      server_queue_drops: 0,
      parse_errors: 0,
    },
    ingest: {
      udp: {
        queue_depth: 0,
        queue_max_depth: 0,
        enqueued_datagrams: 0,
        dropped_datagrams: 0,
        processed_datagrams: 0,
        last_packet_queue_age_ms: 0,
        max_packet_queue_age_ms: 0,
        last_ack_latency_ms: 0,
        max_ack_latency_ms: 0,
      },
      raw_capture: {
        queue_depth: 0,
        queue_max_depth: 0,
        dropped_chunks: 0,
        pressure_state: "ok",
        write_error_chunks: 0,
      },
      ws_publish: {
        active_connections: 0,
        total_publish_ticks: 0,
        last_publish_duration_ms: 0,
        max_publish_duration_ms: 0,
      },
      clients: [],
    },
    intake_stats: {
      last_compute_all_duration_s: 0,
      last_compute_duration_s: 0,
      last_ingest_duration_s: 0,
      total_compute_calls: 0,
      total_ingested_samples: 0,
    },
    persistence: {
      analysis_active_run_id: null,
      analysis_elapsed_s: null,
      analysis_in_progress: false,
      analysis_queue_depth: 0,
      analysis_queue_max_depth: 0,
      analysis_queue_oldest_age_s: null,
      analysis_started_at: null,
      analyzing_oldest_age_s: null,
      analyzing_run_count: 0,
      last_completed_run_error: null,
      last_completed_run_id: null,
      samples_dropped: 0,
      samples_written: 0,
      write_error: null,
    },
    tick_count: 0,
    tick_duration_s: 0,
    max_tick_duration_s: 0,
    ...overrides,
  };
}

export function createUsbInternetStatus(
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
    diagnostic: "No USB network interface is currently detected.",
    ...overrides,
  };
}
