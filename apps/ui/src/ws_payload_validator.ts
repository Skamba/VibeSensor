import * as v from "valibot";

import type {
  LiveWsPayload,
  StrengthMetricPeak,
  StrengthMetricsPayload,
  WsClientInfo,
  WsRotationalSpeeds,
  WsRotationalSpeedValue,
  WsSpectraPayload,
  WsSpectrumSeries,
} from "./contracts/ws_payload_types";
import { parseRuntimeBoundary } from "./runtime_boundary_validation";

function isFiniteNumberArray(input: unknown): input is number[] {
  if (!Array.isArray(input)) {
    return false;
  }
  for (let index = 0; index < input.length; index += 1) {
    const value = input[index];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return false;
    }
  }
  return true;
}

const finiteNumberArraySchema = v.custom<number[]>(
  isFiniteNumberArray,
  "must be an array of finite numbers",
);

const finiteNumberSchema = v.pipe(v.number(), v.finite());
const integerSchema = v.pipe(finiteNumberSchema, v.integer());
const nullableStringSchema = v.nullable(v.string());
const nullableNumberSchema = v.nullable(finiteNumberSchema);
const nullableIntegerSchema = v.nullable(integerSchema);

const strengthPeakSchema = v.looseObject({
  hz: finiteNumberSchema,
  amp: finiteNumberSchema,
  vibration_strength_db: finiteNumberSchema,
  strength_bucket: nullableStringSchema,
});

const strengthMetricsSchema = v.looseObject({
  vibration_strength_db: finiteNumberSchema,
  peak_amp_g: finiteNumberSchema,
  noise_floor_amp_g: finiteNumberSchema,
  strength_bucket: nullableStringSchema,
  top_peaks: v.array(strengthPeakSchema),
});

const wsClientSchema = v.looseObject({
  id: v.string(),
  mac_address: v.string(),
  name: v.string(),
  connected: v.boolean(),
  location_code: v.string(),
  firmware_version: v.string(),
  sample_rate_hz: integerSchema,
  last_seen_age_ms: nullableIntegerSchema,
  frames_total: integerSchema,
  dropped_frames: integerSchema,
  frame_samples: integerSchema,
});

const rotationalSpeedValueSchema = v.looseObject({
  rpm: nullableNumberSchema,
  mode: nullableStringSchema,
  reason: nullableStringSchema,
});

const orderBandSchema = v.looseObject({
  key: v.string(),
  center_hz: finiteNumberSchema,
  tolerance: finiteNumberSchema,
});

const rotationalSpeedsSchema = v.looseObject({
  basis_speed_source: nullableStringSchema,
  wheel: rotationalSpeedValueSchema,
  driveshaft: rotationalSpeedValueSchema,
  engine: rotationalSpeedValueSchema,
  order_bands: v.nullable(v.array(orderBandSchema)),
});

const spectrumSeriesSchema = v.looseObject({
  freq: v.optional(finiteNumberArraySchema),
  combined_spectrum_amp_g: v.optional(finiteNumberArraySchema),
  strength_metrics: v.optional(strengthMetricsSchema),
});

const warningSchema = v.looseObject({
  code: v.string(),
  message: v.string(),
  client_ids: v.array(v.string()),
});

const alignmentSchema = v.looseObject({
  aligned: v.boolean(),
  clock_synced: v.boolean(),
  overlap_ratio: finiteNumberSchema,
  sensor_count: integerSchema,
  shared_window_s: finiteNumberSchema,
});

const spectraSchema = v.looseObject({
  freq: v.optional(finiteNumberArraySchema),
  clients: v.optional(v.record(v.string(), spectrumSeriesSchema)),
  warning: v.optional(warningSchema),
  alignment: v.optional(alignmentSchema),
});

const liveWsPayloadSchema = v.looseObject({
  schema_version: v.string(),
  server_time: v.string(),
  speed_mps: nullableNumberSchema,
  clients: v.array(wsClientSchema),
  selected_client_id: nullableStringSchema,
  rotational_speeds: v.nullable(rotationalSpeedsSchema),
  spectra: v.optional(spectraSchema),
});

export function validateLiveWsPayload(payload: unknown): LiveWsPayload {
  return parseRuntimeBoundary({
    boundary: "websocket payload",
    payload,
    schema: liveWsPayloadSchema,
  });
}

void (strengthPeakSchema satisfies v.GenericSchema<StrengthMetricPeak>);
void (strengthMetricsSchema satisfies v.GenericSchema<StrengthMetricsPayload>);
void (wsClientSchema satisfies v.GenericSchema<WsClientInfo>);
void (rotationalSpeedValueSchema satisfies v.GenericSchema<WsRotationalSpeedValue>);
void (rotationalSpeedsSchema satisfies v.GenericSchema<WsRotationalSpeeds>);
void (spectrumSeriesSchema satisfies v.GenericSchema<WsSpectrumSeries>);
void (spectraSchema satisfies v.GenericSchema<WsSpectraPayload>);
void (liveWsPayloadSchema satisfies v.GenericSchema<LiveWsPayload>);
