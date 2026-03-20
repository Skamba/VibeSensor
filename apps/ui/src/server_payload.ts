import {
  EXPECTED_SCHEMA_VERSION,
  type LiveWsPayload,
  type StrengthMetricPeak,
  type StrengthMetricsPayload,
  type WsClientInfo,
  type WsOrderBand,
  type WsRotationalSpeedValue,
  type WsRotationalSpeeds,
} from "./contracts/ws_payload_types";
import type { SpectrumClientData } from "./app/ui_app_state";
import { validateLiveWsPayload } from "./ws_payload_validator";

type UnknownRecord = Record<string, unknown>;

export type AdaptedClient = Pick<
  WsClientInfo,
  | "id"
  | "name"
  | "connected"
  | "mac_address"
  | "location_code"
  | "last_seen_age_ms"
  | "dropped_frames"
  | "frames_total"
  | "sample_rate_hz"
  | "firmware_version"
>;

export type RotationalSpeedValue = WsRotationalSpeedValue;

export type RotationalSpeeds = WsRotationalSpeeds;

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

function asFiniteNumberArray(value: unknown): number[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is number => typeof entry === "number" && Number.isFinite(entry))
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

function normalizeStrengthMetrics(value: unknown): StrengthMetricsPayload | undefined {
  const record = asRecord(value);
  if (!record) return undefined;
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

function normalizePayloadForValidation(payload: UnknownRecord): LiveWsPayload {
  const spectraRecord = asRecord(payload.spectra);
  if (!spectraRecord) {
    return payload as LiveWsPayload;
  }

  const clientsRecord = asRecord(spectraRecord.clients);
  if (!clientsRecord) {
    return {
      ...payload,
      spectra: spectraRecord as LiveWsPayload["spectra"],
    } as LiveWsPayload;
  }

  const normalizedSpectraClients: Record<string, UnknownRecord> = {};
  for (const [clientId, spectrum] of Object.entries(clientsRecord)) {
    const spectrumRecord = asRecord(spectrum);
    if (!spectrumRecord) {
      normalizedSpectraClients[clientId] = { value: spectrum };
      continue;
    }
    const normalizedSpectrum: UnknownRecord = {
      ...spectrumRecord,
      ...(Array.isArray(spectrumRecord.freq) ? { freq: asFiniteNumberArray(spectrumRecord.freq) } : {}),
      ...(Array.isArray(spectrumRecord.combined_spectrum_amp_g)
        ? { combined_spectrum_amp_g: asFiniteNumberArray(spectrumRecord.combined_spectrum_amp_g) }
        : {}),
    };
    const normalizedStrengthMetrics = normalizeStrengthMetrics(spectrumRecord.strength_metrics);
    if (normalizedStrengthMetrics) {
      normalizedSpectrum.strength_metrics = normalizedStrengthMetrics;
    } else {
      delete normalizedSpectrum.strength_metrics;
    }
    normalizedSpectraClients[clientId] = normalizedSpectrum;
  }

  return {
    ...payload,
    spectra: {
      ...spectraRecord,
      ...(Array.isArray(spectraRecord.freq) ? { freq: asFiniteNumberArray(spectraRecord.freq) } : {}),
      clients: normalizedSpectraClients,
    },
  } as LiveWsPayload;
}

function adaptClient(client: WsClientInfo): AdaptedClient {
  return {
    id: client.id,
    name: client.name,
    connected: client.connected,
    mac_address: client.mac_address,
    location_code: client.location_code,
    last_seen_age_ms: client.last_seen_age_ms,
    dropped_frames: client.dropped_frames,
    frames_total: client.frames_total,
    sample_rate_hz: client.sample_rate_hz,
    firmware_version: client.firmware_version,
  };
}

function adaptRotationalSpeeds(
  rotationalSpeeds: LiveWsPayload["rotational_speeds"],
): RotationalSpeeds | null {
  if (!rotationalSpeeds) {
    return null;
  }
  return {
    basis_speed_source: rotationalSpeeds.basis_speed_source,
    wheel: rotationalSpeeds.wheel,
    driveshaft: rotationalSpeeds.driveshaft,
    engine: rotationalSpeeds.engine,
    order_bands: rotationalSpeeds.order_bands?.map((band: WsOrderBand): OrderBand => band) ?? null,
  };
}

function adaptSpectra(spectra: LiveWsPayload["spectra"]): AdaptedPayload["spectra"] | null {
  if (!spectra?.clients) return null;
  const sharedFreq = spectra.freq ?? [];

  const adaptedClients: Record<string, SpectrumClientData> = {};
  for (const [clientId, spectrum] of Object.entries(spectra.clients)) {
    const rawPerClientFreq = spectrum.freq ?? [];
    const freq = rawPerClientFreq.length > 0 ? rawPerClientFreq : sharedFreq;
    const combined = spectrum.combined_spectrum_amp_g ?? [];
    const strengthMetrics = spectrum.strength_metrics ?? null;
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

  const validatedPayload = validateLiveWsPayload(normalizePayloadForValidation(payloadRecord));

  const schemaVersion = validatedPayload.schema_version ?? null;
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

  return {
    clients: validatedPayload.clients?.map(adaptClient) ?? [],
    speed_mps: validatedPayload.speed_mps ?? null,
    rotational_speeds: adaptRotationalSpeeds(validatedPayload.rotational_speeds),
    spectra: adaptSpectra(validatedPayload.spectra),
  };
}
