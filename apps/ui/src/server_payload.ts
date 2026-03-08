import type { StrengthBand } from "./diagnostics";
import {
  EXPECTED_SCHEMA_VERSION,
  type StrengthMetricPeak,
  type StrengthMetricsPayload,
  type WsDiagnosticEvent,
  type WsDiagnosticLevel,
  type WsDiagnosticsPayload,
  type WsOrderBand,
} from "./contracts/ws_payload_types";

type UnknownRecord = Record<string, unknown>;

export type AdaptedSpectrum = {
  freq: number[];
  combined: number[];
  strength_metrics: StrengthMetricsPayload;
};

export type AdaptedClient = {
  id: string;
  name: string;
  connected: boolean;
  mac_address: string;
  location_code: string;
  last_seen_age_ms: number | null;
  dropped_frames: number | null;
  frames_total: number | null;
  sample_rate_hz: number;
  firmware_version: string;
};

export type MatrixCell = WsDiagnosticsPayload["matrix"][string][string];
export type DiagnosticEvent = WsDiagnosticEvent;
export type DiagnosticLevel = WsDiagnosticLevel;
export type DiagnosticLevels = WsDiagnosticsPayload["levels"];

export type RotationalSpeedValue = {
  rpm: number | null;
  mode: string | null;
  reason: string | null;
};

export type RotationalSpeeds = {
  basis_speed_source: string | null;
  wheel: RotationalSpeedValue;
  driveshaft: RotationalSpeedValue;
  engine: RotationalSpeedValue;
  order_bands: OrderBand[] | null;
};

export type OrderBand = WsOrderBand;

export type AdaptedPayload = {
  clients: AdaptedClient[];
  speed_mps: number | null;
  rotational_speeds: RotationalSpeeds | null;
  diagnostics: {
    diagnostics_sequence: number;
    strength_bands: StrengthBand[];
    matrix: Record<string, Record<string, MatrixCell>> | null;
    events: DiagnosticEvent[];
    levels: DiagnosticLevels;
  };
  spectra: {
    clients: Record<string, AdaptedSpectrum>;
  } | null;
};

function asRecord(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" ? (value as UnknownRecord) : null;
}

function getString(record: UnknownRecord, key: string): string | null {
  return typeof record[key] === "string" ? String(record[key]) : null;
}

function getNumber(record: UnknownRecord, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function getBoolean(record: UnknownRecord, key: string): boolean {
  return Boolean(record[key]);
}

function asNumberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.map((v) => Number(v)).filter((v) => Number.isFinite(v))
    : [];
}

function emptyStrengthMetrics(): StrengthMetricsPayload {
  return {
    combined_spectrum_amp_g: [],
    vibration_strength_db: 0,
    peak_amp_g: 0,
    noise_floor_amp_g: 0,
    strength_bucket: null,
    top_peaks: [],
  };
}

function parseStrengthMetricPeak(value: unknown): StrengthMetricPeak | null {
  const record = asRecord(value);
  if (!record) return null;
  const hz = getNumber(record, "hz");
  const amp = getNumber(record, "amp");
  const vibrationStrengthDb = getNumber(record, "vibration_strength_db");
  if (hz === null || amp === null || vibrationStrengthDb === null) return null;
  return {
    hz,
    amp,
    vibration_strength_db: vibrationStrengthDb,
    strength_bucket: getString(record, "strength_bucket"),
  };
}

function parseStrengthMetrics(value: unknown): StrengthMetricsPayload | null {
  const record = asRecord(value);
  if (!record) return null;
  const defaults = emptyStrengthMetrics();
  const topPeaks = Array.isArray(record.top_peaks)
    ? record.top_peaks
        .map((peak) => parseStrengthMetricPeak(peak))
        .filter((peak): peak is StrengthMetricPeak => peak !== null)
    : [];
  return {
    combined_spectrum_amp_g: asNumberArray(record.combined_spectrum_amp_g),
    vibration_strength_db: getNumber(record, "vibration_strength_db") ?? defaults.vibration_strength_db,
    peak_amp_g: getNumber(record, "peak_amp_g") ?? defaults.peak_amp_g,
    noise_floor_amp_g: getNumber(record, "noise_floor_amp_g") ?? defaults.noise_floor_amp_g,
    strength_bucket: getString(record, "strength_bucket") ?? defaults.strength_bucket,
    top_peaks: topPeaks,
  };
}

function parseRotationalSpeedValue(value: unknown): RotationalSpeedValue {
  const record = asRecord(value);
  if (!record) {
    return { rpm: null, mode: null, reason: null };
  }
  return {
    rpm: getNumber(record, "rpm"),
    mode: getString(record, "mode"),
    reason: getString(record, "reason"),
  };
}

function parseOrderBand(value: unknown): OrderBand | null {
  const record = asRecord(value);
  if (!record) return null;
  const key = getString(record, "key");
  const centerHz = getNumber(record, "center_hz");
  const tolerance = getNumber(record, "tolerance");
  if (key === null || centerHz === null || tolerance === null) return null;
  return { key, center_hz: centerHz, tolerance };
}

function parseDiagnosticEvent(value: unknown): DiagnosticEvent | null {
  const record = asRecord(value);
  if (!record) return null;
  const kind = getString(record, "kind");
  const classKey = getString(record, "class_key");
  const sensorId = getString(record, "sensor_id");
  const sensorLabel = getString(record, "sensor_label");
  const peakHz = getNumber(record, "peak_hz");
  const peakAmp = getNumber(record, "peak_amp");
  const peakAmpG = getNumber(record, "peak_amp_g");
  const vibrationStrengthDb = getNumber(record, "vibration_strength_db");
  if (
    kind === null ||
    classKey === null ||
    sensorId === null ||
    sensorLabel === null ||
    peakHz === null ||
    peakAmp === null ||
    peakAmpG === null ||
    vibrationStrengthDb === null
  ) {
    return null;
  }
  return {
    event_id: getNumber(record, "event_id") ?? undefined,
    kind,
    class_key: classKey,
    severity_key: getString(record, "severity_key"),
    sensor_id: sensorId,
    sensor_label: sensorLabel,
    sensor_labels: Array.isArray(record.sensor_labels)
      ? record.sensor_labels.filter((label): label is string => typeof label === "string")
      : [],
    sensor_count: getNumber(record, "sensor_count") ?? 0,
    peak_hz: peakHz,
    peak_amp: peakAmp,
    peak_amp_g: peakAmpG,
    vibration_strength_db: vibrationStrengthDb,
  };
}

function parseDiagnosticLevel(value: unknown): DiagnosticLevel | null {
  const record = asRecord(value);
  if (!record) return null;
  return {
    bucket_key: getString(record, "bucket_key") ?? undefined,
    strength_db: getNumber(record, "strength_db") ?? undefined,
    sensor_label: getString(record, "sensor_label") ?? undefined,
    sensor_location: getString(record, "sensor_location") ?? undefined,
    class_key: getString(record, "class_key") ?? undefined,
    peak_hz: getNumber(record, "peak_hz") ?? undefined,
    confidence: getNumber(record, "confidence") ?? undefined,
    agreement_count: getNumber(record, "agreement_count") ?? undefined,
    sensor_count: getNumber(record, "sensor_count") ?? undefined,
  };
}

function parseDiagnosticLevelMap(value: unknown): Record<string, DiagnosticLevel> {
  const record = asRecord(value);
  if (!record) return {};
  const parsed: Record<string, DiagnosticLevel> = {};
  for (const [key, entry] of Object.entries(record)) {
    const level = parseDiagnosticLevel(entry);
    if (level) parsed[key] = level;
  }
  return parsed;
}

function parseMatrix(value: unknown): AdaptedPayload["diagnostics"]["matrix"] | null {
  const record = asRecord(value);
  if (!record) return null;
  const matrix: Record<string, Record<string, MatrixCell>> = {};
  for (const [sourceKey, columns] of Object.entries(record)) {
    const columnRecord = asRecord(columns);
    if (!columnRecord) continue;
    const cells: Record<string, MatrixCell> = {};
    for (const [severityKey, cellValue] of Object.entries(columnRecord)) {
      const cellRecord = asRecord(cellValue);
      if (!cellRecord) continue;
      cells[severityKey] = {
        count: getNumber(cellRecord, "count") ?? 0,
        seconds: getNumber(cellRecord, "seconds") ?? 0,
        contributors: asRecord(cellRecord.contributors)
          ? Object.fromEntries(
              Object.entries(asRecord(cellRecord.contributors)!)
                .map(([name, count]) => [name, Number(count)])
                .filter(([, count]) => Number.isFinite(count)),
            )
          : {},
      };
    }
    matrix[sourceKey] = cells;
  }
  return matrix;
}

function parseStrengthBands(value: unknown): StrengthBand[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((band) => {
      const record = asRecord(band);
      if (!record) return null;
      const key = getString(record, "key");
      const minDb = getNumber(record, "min_db");
      if (key === null || minDb === null) return null;
      const parsed: StrengthBand = { key, min_db: minDb };
      const maxDb = getNumber(record, "max_db");
      const labelKey = getString(record, "labelKey");
      if (maxDb !== null) parsed.max_db = maxDb;
      if (labelKey !== null) parsed.labelKey = labelKey;
      return parsed;
    })
    .filter((band): band is StrengthBand => band !== null);
}

function parseClient(value: unknown): AdaptedClient | null {
  const record = asRecord(value);
  if (!record) return null;
  const id = getString(record, "id");
  const name = getString(record, "name");
  if (id === null || name === null) return null;
  const locationCode = getString(record, "location_code")
    ?? getString(record, "location")
    ?? "";
  return {
    id,
    name,
    connected: getBoolean(record, "connected"),
    mac_address: getString(record, "mac_address") ?? "",
    location_code: locationCode,
    last_seen_age_ms: getNumber(record, "last_seen_age_ms"),
    dropped_frames: getNumber(record, "dropped_frames"),
    frames_total: getNumber(record, "frames_total"),
    sample_rate_hz: getNumber(record, "sample_rate_hz") ?? 0,
    firmware_version: getString(record, "firmware_version") ?? "",
  };
}

function parseSpectra(value: unknown): AdaptedPayload["spectra"] | null {
  const record = asRecord(value);
  if (!record) return null;
  const sharedFreq = asNumberArray(record.freq);
  const clientsRecord = asRecord(record.clients);
  if (!clientsRecord) return null;

  const adaptedClients: Record<string, AdaptedSpectrum> = {};
  for (const [clientId, spectrum] of Object.entries(clientsRecord)) {
    const spectrumRecord = asRecord(spectrum);
    if (!spectrumRecord) continue;
    const rawPerClientFreq = asNumberArray(spectrumRecord.freq);
    const freq = rawPerClientFreq.length > 0 ? rawPerClientFreq : sharedFreq;
    const combined = asNumberArray(spectrumRecord.combined_spectrum_amp_g);
    const strengthMetrics = parseStrengthMetrics(spectrumRecord.strength_metrics);
    if (!freq.length || !combined.length || strengthMetrics === null) continue;
    adaptedClients[clientId] = {
      freq,
      combined,
      strength_metrics: strengthMetrics,
    };
  }

  return { clients: adaptedClients };
}

let schemaWarningLogged = false;

export function adaptServerPayload(payload: unknown): AdaptedPayload {
  const payloadRecord = asRecord(payload);
  if (!payloadRecord) {
    throw new Error("Missing websocket payload.");
  }

  const schemaVersion = getString(payloadRecord, "schema_version");
  if (
    schemaVersion !== null &&
    schemaVersion !== EXPECTED_SCHEMA_VERSION &&
    !schemaWarningLogged
  ) {
    schemaWarningLogged = true;
    console.error(
      `[VibeSensor] Unknown WS payload schema_version "${schemaVersion}" ` +
      `(expected "${EXPECTED_SCHEMA_VERSION}"). The dashboard may not display correctly. ` +
      "Update the UI to match the server version.",
    );
  }

  const diagnosticsRecord = asRecord(payloadRecord.diagnostics);
  if (!diagnosticsRecord) {
    throw new Error("Missing diagnostics payload from server.");
  }

  const clients = Array.isArray(payloadRecord.clients)
    ? payloadRecord.clients
        .map((client) => parseClient(client))
        .filter((client): client is AdaptedClient => client !== null)
    : [];

  const rotationalRecord = asRecord(payloadRecord.rotational_speeds);
  const rotationalSpeeds: RotationalSpeeds | null = rotationalRecord
    ? {
        basis_speed_source: getString(rotationalRecord, "basis_speed_source"),
        wheel: parseRotationalSpeedValue(rotationalRecord.wheel),
        driveshaft: parseRotationalSpeedValue(rotationalRecord.driveshaft),
        engine: parseRotationalSpeedValue(rotationalRecord.engine),
        order_bands: Array.isArray(rotationalRecord.order_bands)
          ? rotationalRecord.order_bands
              .map((band) => parseOrderBand(band))
              .filter((band): band is OrderBand => band !== null)
          : null,
      }
    : null;

  return {
    clients,
    speed_mps: getNumber(payloadRecord, "speed_mps"),
    rotational_speeds: rotationalSpeeds,
    diagnostics: {
      diagnostics_sequence: getNumber(diagnosticsRecord, "diagnostics_sequence") ?? -1,
      strength_bands: parseStrengthBands(diagnosticsRecord.strength_bands),
      matrix: parseMatrix(diagnosticsRecord.matrix),
      events: Array.isArray(diagnosticsRecord.events)
        ? diagnosticsRecord.events
            .map((event) => parseDiagnosticEvent(event))
            .filter((event): event is DiagnosticEvent => event !== null)
        : [],
      levels: {
        by_source: parseDiagnosticLevelMap(asRecord(diagnosticsRecord.levels)?.by_source),
        by_sensor: parseDiagnosticLevelMap(asRecord(diagnosticsRecord.levels)?.by_sensor),
        by_location: parseDiagnosticLevelMap(asRecord(diagnosticsRecord.levels)?.by_location),
      },
    },
    spectra: parseSpectra(payloadRecord.spectra),
  };
}
