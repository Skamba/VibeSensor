import * as v from "valibot";

import type {
  HealthStatusPayload,
  UpdateIssue,
  UpdateStatusPayload,
  UsbInternetStatusPayload,
} from "./types";
import { parseRuntimeBoundary } from "../runtime_boundary_validation";

const finiteNumberSchema = v.pipe(v.number(), v.finite());
const integerSchema = v.pipe(finiteNumberSchema, v.integer());
const nullableStringSchema = v.nullable(v.string());
const nullableFiniteNumberSchema = v.nullable(finiteNumberSchema);

const updateStateSchema = v.picklist(["idle", "running", "success", "failed"]);
const updateTransportSchema = v.picklist(["wifi", "usb_internet"]);
const healthStatusSchema = v.picklist(["ok", "warn", "degraded"]);
const subsystemHealthStatusSchema = v.picklist([
  "ready",
  "degraded",
  "unhealthy",
]);
const rawCapturePressureStateSchema = v.picklist(["ok", "warn", "degraded"]);

const stringMapSchema = v.record(v.string(), v.string());
const integerMapSchema = v.record(v.string(), integerSchema);

const updateIssueSchema = v.looseObject({
  detail: v.string(),
  message: v.string(),
  phase: v.string(),
});

const updateRuntimeSchema = v.looseObject({
  assets_verified: v.boolean(),
  commit: v.string(),
  has_packaged_static: v.boolean(),
  static_assets_hash: v.string(),
  static_build_commit: v.string(),
  static_build_source_hash: v.string(),
  ui_source_hash: v.string(),
  version: v.string(),
});

const updateStatusPayloadSchema = v.looseObject({
  exit_code: v.optional(v.nullable(integerSchema)),
  finished_at: v.optional(nullableFiniteNumberSchema),
  issues: v.array(updateIssueSchema),
  last_success_at: v.optional(nullableFiniteNumberSchema),
  log_tail: v.array(v.string()),
  phase: v.string(),
  phase_elapsed_s: v.optional(nullableFiniteNumberSchema),
  phase_started_at: v.optional(nullableFiniteNumberSchema),
  runtime: updateRuntimeSchema,
  ssid: v.optional(nullableStringSchema),
  started_at: v.optional(nullableFiniteNumberSchema),
  state: updateStateSchema,
  transport: updateTransportSchema,
  updated_at: v.optional(nullableFiniteNumberSchema),
  uplink_interface: v.optional(nullableStringSchema),
});

const usbInternetStatusPayloadSchema = v.looseObject({
  connection_name: v.optional(nullableStringSchema),
  detected: v.boolean(),
  diagnostic: v.string(),
  driver: v.optional(nullableStringSchema),
  gateway: v.optional(nullableStringSchema),
  has_default_route: v.boolean(),
  interface_name: v.optional(nullableStringSchema),
  ipv4_addresses: v.array(v.string()),
  usable: v.boolean(),
});

const healthDataLossSchema = v.looseObject({
  affected_clients: integerSchema,
  buffer_overflow_drops: integerSchema,
  frames_dropped: integerSchema,
  parse_errors: integerSchema,
  queue_overflow_drops: integerSchema,
  server_queue_drops: integerSchema,
  tracked_clients: integerSchema,
});

const healthIntakeStatsSchema = v.looseObject({
  last_compute_all_duration_s: finiteNumberSchema,
  last_compute_duration_s: finiteNumberSchema,
  last_ingest_duration_s: finiteNumberSchema,
  total_compute_calls: integerSchema,
  total_ingested_samples: integerSchema,
});

const healthPersistenceSchema = v.looseObject({
  analysis_active_run_id: v.optional(nullableStringSchema),
  analysis_elapsed_s: v.optional(nullableFiniteNumberSchema),
  analysis_in_progress: v.boolean(),
  analysis_queue_depth: integerSchema,
  analysis_queue_max_depth: integerSchema,
  analysis_queue_oldest_age_s: v.optional(nullableFiniteNumberSchema),
  analysis_started_at: v.optional(nullableFiniteNumberSchema),
  analyzing_oldest_age_s: v.optional(nullableFiniteNumberSchema),
  analyzing_run_count: integerSchema,
  last_completed_run_error: v.optional(nullableStringSchema),
  last_completed_run_id: v.optional(nullableStringSchema),
  samples_dropped: integerSchema,
  samples_written: integerSchema,
  write_error: nullableStringSchema,
});

const healthUdpIngestSchema = v.looseObject({
  dropped_datagrams: integerSchema,
  enqueued_datagrams: integerSchema,
  last_ack_latency_ms: finiteNumberSchema,
  last_packet_queue_age_ms: finiteNumberSchema,
  max_ack_latency_ms: finiteNumberSchema,
  max_packet_queue_age_ms: finiteNumberSchema,
  processed_datagrams: integerSchema,
  queue_depth: integerSchema,
  queue_max_depth: integerSchema,
});

const healthRawCaptureSchema = v.looseObject({
  dropped_chunks: integerSchema,
  pressure_state: rawCapturePressureStateSchema,
  queue_depth: integerSchema,
  queue_max_depth: integerSchema,
  write_error_chunks: integerSchema,
});

const healthWsPublishSchema = v.looseObject({
  active_connections: integerSchema,
  last_publish_duration_ms: finiteNumberSchema,
  max_publish_duration_ms: finiteNumberSchema,
  total_publish_ticks: integerSchema,
});

const healthIngestClientSchema = v.looseObject({
  advertised_sample_rate_hz: integerSchema,
  client_id: v.string(),
  duplicates_received: integerSchema,
  estimated_ingest_hz: finiteNumberSchema,
  frames_dropped: integerSchema,
  last_ack_latency_ms: finiteNumberSchema,
  last_packet_queue_age_ms: finiteNumberSchema,
  late_packets: integerSchema,
  parse_errors: integerSchema,
  processed_packets: integerSchema,
  processed_samples: integerSchema,
  queue_overflow_drops: integerSchema,
  server_queue_drops: integerSchema,
});

const healthIngestSchema = v.looseObject({
  clients: v.array(healthIngestClientSchema),
  raw_capture: healthRawCaptureSchema,
  udp: healthUdpIngestSchema,
  ws_publish: healthWsPublishSchema,
});

const healthSubsystemSchema = v.looseObject({
  reason_codes: v.array(v.string()),
  status: subsystemHealthStatusSchema,
});

const healthStatusPayloadSchema = v.looseObject({
  background_task_failures: stringMapSchema,
  data_loss: healthDataLossSchema,
  db_corruption_detected: v.boolean(),
  db_engine_unhealthy: v.boolean(),
  db_engine_unhealthy_details: nullableStringSchema,
  db_engine_unhealthy_reason: nullableStringSchema,
  db_last_write_duration_s: finiteNumberSchema,
  db_max_write_duration_s: finiteNumberSchema,
  degradation_reasons: v.array(v.string()),
  frame_size_mismatch_count: integerSchema,
  ingest: healthIngestSchema,
  intake_stats: healthIntakeStatsSchema,
  max_tick_duration_s: finiteNumberSchema,
  persistence: healthPersistenceSchema,
  processing_failure_categories: integerMapSchema,
  processing_failures: integerSchema,
  processing_last_failure: nullableStringSchema,
  processing_state: v.string(),
  sample_rate_mismatch_count: integerSchema,
  startup_error: nullableStringSchema,
  startup_phase: v.string(),
  startup_state: v.string(),
  startup_warnings: v.array(v.string()),
  status: healthStatusSchema,
  subsystems: v.record(v.string(), healthSubsystemSchema),
  tick_count: integerSchema,
  tick_duration_s: finiteNumberSchema,
});

export function parseUpdateStatusPayload(
  payload: unknown,
): UpdateStatusPayload {
  return parseRuntimeBoundary({
    boundary: "update status response",
    payload,
    schema: updateStatusPayloadSchema,
  });
}

export function parseUsbInternetStatusPayload(
  payload: unknown,
): UsbInternetStatusPayload {
  return parseRuntimeBoundary({
    boundary: "USB internet status response",
    payload,
    schema: usbInternetStatusPayloadSchema,
  });
}

export function parseHealthStatusPayload(
  payload: unknown,
): HealthStatusPayload {
  return parseRuntimeBoundary({
    boundary: "health status response",
    payload,
    schema: healthStatusPayloadSchema,
  });
}

void (updateIssueSchema satisfies v.GenericSchema<UpdateIssue>);
void (updateStatusPayloadSchema satisfies v.GenericSchema<UpdateStatusPayload>);
void (usbInternetStatusPayloadSchema satisfies v.GenericSchema<UsbInternetStatusPayload>);
void (healthStatusPayloadSchema satisfies v.GenericSchema<HealthStatusPayload>);
