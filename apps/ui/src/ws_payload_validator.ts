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

type JsonRecord = Record<string, unknown>;

function invalidPayload(path: string, message: string): never {
  throw new Error(`Invalid websocket payload: ${path} ${message}`);
}

function requireRecord(value: unknown, path: string): JsonRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    invalidPayload(path, "must be an object");
  }
  return value as JsonRecord;
}

function requireProperty(
  record: JsonRecord,
  key: string,
  path: string,
): unknown {
  if (!(key in record)) {
    invalidPayload(path, "is required");
  }
  return record[key];
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== "string") {
    invalidPayload(path, "must be a string");
  }
  return value;
}

function requireBoolean(value: unknown, path: string): boolean {
  if (typeof value !== "boolean") {
    invalidPayload(path, "must be a boolean");
  }
  return value;
}

function requireFiniteNumber(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    invalidPayload(path, "must be a finite number");
  }
  return value;
}

function requireInteger(value: unknown, path: string): number {
  const numberValue = requireFiniteNumber(value, path);
  if (!Number.isInteger(numberValue)) {
    invalidPayload(path, "must be an integer");
  }
  return numberValue;
}

function requireNullableString(value: unknown, path: string): string | null {
  if (value === null) {
    return null;
  }
  return requireString(value, path);
}

function requireNullableNumber(value: unknown, path: string): number | null {
  if (value === null) {
    return null;
  }
  return requireFiniteNumber(value, path);
}

function requireNullableInteger(value: unknown, path: string): number | null {
  if (value === null) {
    return null;
  }
  return requireInteger(value, path);
}

function requireArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    invalidPayload(path, "must be an array");
  }
  return value;
}

function validateNumberArray(value: unknown, path: string): number[] {
  const array = requireArray(value, path);
  for (let index = 0; index < array.length; index += 1) {
    requireFiniteNumber(array[index], `${path}/${index}`);
  }
  return array as number[];
}

function validateStringArray(value: unknown, path: string): string[] {
  const array = requireArray(value, path);
  for (let index = 0; index < array.length; index += 1) {
    requireString(array[index], `${path}/${index}`);
  }
  return array as string[];
}

function validateStrengthPeak(
  value: unknown,
  path: string,
): StrengthMetricPeak {
  const record = requireRecord(value, path);
  requireFiniteNumber(
    requireProperty(record, "hz", `${path}/hz`),
    `${path}/hz`,
  );
  requireFiniteNumber(
    requireProperty(record, "amp", `${path}/amp`),
    `${path}/amp`,
  );
  requireFiniteNumber(
    requireProperty(
      record,
      "vibration_strength_db",
      `${path}/vibration_strength_db`,
    ),
    `${path}/vibration_strength_db`,
  );
  requireNullableString(
    requireProperty(record, "strength_bucket", `${path}/strength_bucket`),
    `${path}/strength_bucket`,
  );
  return value as StrengthMetricPeak;
}

function validateStrengthMetrics(
  value: unknown,
  path: string,
): StrengthMetricsPayload {
  const record = requireRecord(value, path);
  requireFiniteNumber(
    requireProperty(
      record,
      "vibration_strength_db",
      `${path}/vibration_strength_db`,
    ),
    `${path}/vibration_strength_db`,
  );
  requireFiniteNumber(
    requireProperty(record, "peak_amp_g", `${path}/peak_amp_g`),
    `${path}/peak_amp_g`,
  );
  requireFiniteNumber(
    requireProperty(record, "noise_floor_amp_g", `${path}/noise_floor_amp_g`),
    `${path}/noise_floor_amp_g`,
  );
  requireNullableString(
    requireProperty(record, "strength_bucket", `${path}/strength_bucket`),
    `${path}/strength_bucket`,
  );
  const topPeaks = requireArray(
    requireProperty(record, "top_peaks", `${path}/top_peaks`),
    `${path}/top_peaks`,
  );
  for (let index = 0; index < topPeaks.length; index += 1) {
    validateStrengthPeak(topPeaks[index], `${path}/top_peaks/${index}`);
  }
  return value as StrengthMetricsPayload;
}

function validateWsClient(value: unknown, path: string): WsClientInfo {
  const record = requireRecord(value, path);
  requireString(requireProperty(record, "id", `${path}/id`), `${path}/id`);
  requireString(
    requireProperty(record, "mac_address", `${path}/mac_address`),
    `${path}/mac_address`,
  );
  requireString(
    requireProperty(record, "name", `${path}/name`),
    `${path}/name`,
  );
  requireBoolean(
    requireProperty(record, "connected", `${path}/connected`),
    `${path}/connected`,
  );
  requireString(
    requireProperty(record, "location_code", `${path}/location_code`),
    `${path}/location_code`,
  );
  requireString(
    requireProperty(record, "firmware_version", `${path}/firmware_version`),
    `${path}/firmware_version`,
  );
  requireInteger(
    requireProperty(record, "sample_rate_hz", `${path}/sample_rate_hz`),
    `${path}/sample_rate_hz`,
  );
  requireNullableInteger(
    requireProperty(record, "last_seen_age_ms", `${path}/last_seen_age_ms`),
    `${path}/last_seen_age_ms`,
  );
  requireInteger(
    requireProperty(record, "frames_total", `${path}/frames_total`),
    `${path}/frames_total`,
  );
  requireInteger(
    requireProperty(record, "dropped_frames", `${path}/dropped_frames`),
    `${path}/dropped_frames`,
  );
  return value as WsClientInfo;
}

function validateRotationalSpeedValue(
  value: unknown,
  path: string,
): WsRotationalSpeedValue {
  const record = requireRecord(value, path);
  requireNullableNumber(
    requireProperty(record, "rpm", `${path}/rpm`),
    `${path}/rpm`,
  );
  requireNullableString(
    requireProperty(record, "mode", `${path}/mode`),
    `${path}/mode`,
  );
  requireNullableString(
    requireProperty(record, "reason", `${path}/reason`),
    `${path}/reason`,
  );
  return value as WsRotationalSpeedValue;
}

function validateOrderBand(value: unknown, path: string): void {
  const record = requireRecord(value, path);
  requireString(requireProperty(record, "key", `${path}/key`), `${path}/key`);
  requireFiniteNumber(
    requireProperty(record, "center_hz", `${path}/center_hz`),
    `${path}/center_hz`,
  );
  requireFiniteNumber(
    requireProperty(record, "tolerance", `${path}/tolerance`),
    `${path}/tolerance`,
  );
}

function validateRotationalSpeeds(
  value: unknown,
  path: string,
): WsRotationalSpeeds {
  const record = requireRecord(value, path);
  requireNullableString(
    requireProperty(record, "basis_speed_source", `${path}/basis_speed_source`),
    `${path}/basis_speed_source`,
  );
  validateRotationalSpeedValue(
    requireProperty(record, "wheel", `${path}/wheel`),
    `${path}/wheel`,
  );
  validateRotationalSpeedValue(
    requireProperty(record, "driveshaft", `${path}/driveshaft`),
    `${path}/driveshaft`,
  );
  validateRotationalSpeedValue(
    requireProperty(record, "engine", `${path}/engine`),
    `${path}/engine`,
  );
  const orderBands = requireProperty(
    record,
    "order_bands",
    `${path}/order_bands`,
  );
  if (orderBands !== null) {
    const bands = requireArray(orderBands, `${path}/order_bands`);
    for (let index = 0; index < bands.length; index += 1) {
      validateOrderBand(bands[index], `${path}/order_bands/${index}`);
    }
  }
  return value as WsRotationalSpeeds;
}

function validateSpectrumSeries(
  value: unknown,
  path: string,
): WsSpectrumSeries {
  const record = requireRecord(value, path);
  if ("freq" in record && record.freq !== undefined) {
    validateNumberArray(record.freq, `${path}/freq`);
  }
  if (
    "combined_spectrum_amp_g" in record &&
    record.combined_spectrum_amp_g !== undefined
  ) {
    validateNumberArray(
      record.combined_spectrum_amp_g,
      `${path}/combined_spectrum_amp_g`,
    );
  }
  if ("strength_metrics" in record && record.strength_metrics !== undefined) {
    validateStrengthMetrics(
      record.strength_metrics,
      `${path}/strength_metrics`,
    );
  }
  return value as WsSpectrumSeries;
}

function validateSpectra(value: unknown, path: string): WsSpectraPayload {
  const record = requireRecord(value, path);
  if ("freq" in record && record.freq !== undefined) {
    validateNumberArray(record.freq, `${path}/freq`);
  }
  if ("clients" in record && record.clients !== undefined) {
    const clients = requireRecord(record.clients, `${path}/clients`);
    for (const [clientId, series] of Object.entries(clients)) {
      validateSpectrumSeries(series, `${path}/clients/${clientId}`);
    }
  }
  if ("warning" in record && record.warning !== undefined) {
    const warning = requireRecord(record.warning, `${path}/warning`);
    requireString(
      requireProperty(warning, "code", `${path}/warning/code`),
      `${path}/warning/code`,
    );
    requireString(
      requireProperty(warning, "message", `${path}/warning/message`),
      `${path}/warning/message`,
    );
    validateStringArray(
      requireProperty(warning, "client_ids", `${path}/warning/client_ids`),
      `${path}/warning/client_ids`,
    );
  }
  if ("alignment" in record && record.alignment !== undefined) {
    const alignment = requireRecord(record.alignment, `${path}/alignment`);
    requireBoolean(
      requireProperty(alignment, "aligned", `${path}/alignment/aligned`),
      `${path}/alignment/aligned`,
    );
    requireBoolean(
      requireProperty(
        alignment,
        "clock_synced",
        `${path}/alignment/clock_synced`,
      ),
      `${path}/alignment/clock_synced`,
    );
    requireFiniteNumber(
      requireProperty(
        alignment,
        "overlap_ratio",
        `${path}/alignment/overlap_ratio`,
      ),
      `${path}/alignment/overlap_ratio`,
    );
    requireInteger(
      requireProperty(
        alignment,
        "sensor_count",
        `${path}/alignment/sensor_count`,
      ),
      `${path}/alignment/sensor_count`,
    );
    requireFiniteNumber(
      requireProperty(
        alignment,
        "shared_window_s",
        `${path}/alignment/shared_window_s`,
      ),
      `${path}/alignment/shared_window_s`,
    );
  }
  return value as WsSpectraPayload;
}

export function validateLiveWsPayload(payload: unknown): LiveWsPayload {
  const record = requireRecord(payload, "/");
  requireString(
    requireProperty(record, "schema_version", "/schema_version"),
    "/schema_version",
  );
  requireString(
    requireProperty(record, "server_time", "/server_time"),
    "/server_time",
  );
  requireNullableNumber(
    requireProperty(record, "speed_mps", "/speed_mps"),
    "/speed_mps",
  );
  const clients = requireArray(
    requireProperty(record, "clients", "/clients"),
    "/clients",
  );
  for (let index = 0; index < clients.length; index += 1) {
    validateWsClient(clients[index], `/clients/${index}`);
  }
  requireNullableString(
    requireProperty(record, "selected_client_id", "/selected_client_id"),
    "/selected_client_id",
  );
  const rotationalSpeeds = requireProperty(
    record,
    "rotational_speeds",
    "/rotational_speeds",
  );
  if (rotationalSpeeds !== null) {
    validateRotationalSpeeds(rotationalSpeeds, "/rotational_speeds");
  }
  if ("spectra" in record && record.spectra !== undefined) {
    validateSpectra(record.spectra, "/spectra");
  }
  return payload as LiveWsPayload;
}
