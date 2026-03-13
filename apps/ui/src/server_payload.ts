import {
  EXPECTED_SCHEMA_VERSION,
  type StrengthMetricPeak,
  type StrengthMetricsPayload,
  type WsOrderBand,
} from "./contracts/ws_payload_types";
import type { SpectrumClientData } from "./app/ui_app_state";

type UnknownRecord = Record<string, unknown>;

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
  spectra: {
    clients: Record<string, SpectrumClientData>;
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

function parseClient(value: unknown): AdaptedClient | null {
  const record = asRecord(value);
  if (!record) return null;
  const id = getString(record, "id");
  const name = getString(record, "name");
  if (id === null || name === null) return null;
  const locationCode = getString(record, "location_code") ?? "";
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

  const adaptedClients: Record<string, SpectrumClientData> = {};
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
    spectra: parseSpectra(payloadRecord.spectra),
  };
}
