import {
  EXPECTED_SCHEMA_VERSION,
  type LiveWsPayload,
  type WsClientInfo,
  type WsOrderBand,
  type WsRotationalSpeedValue,
  type WsRotationalSpeeds,
} from "./contracts/ws_payload_types";
import type { SpectrumClientData } from "./app/ui_app_state";
import { validateLiveWsPayload } from "./ws_payload_validator";

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

function hasCompleteSpectrumData(
  freq: number[],
  combined: number[],
  strengthMetrics: SpectrumClientData["strength_metrics"] | null,
): strengthMetrics is NonNullable<SpectrumClientData["strength_metrics"]> {
  return freq.length > 0 && combined.length > 0 && strengthMetrics !== null && freq.length === combined.length;
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
    if (!hasCompleteSpectrumData(freq, combined, strengthMetrics)) {
      continue;
    }
    adaptedClients[clientId] = {
      freq,
      combined,
      strength_metrics: strengthMetrics,
    };
  }

  return { clients: adaptedClients };
}

let schemaWarningLogged = false;

function warnOnUnknownSchemaVersion(schemaVersion: string): void {
  if (schemaVersion !== EXPECTED_SCHEMA_VERSION && !schemaWarningLogged) {
    schemaWarningLogged = true;
    console.error(
      `[VibeSensor] Unknown WS payload schema_version "${schemaVersion}" ` +
      `(expected "${EXPECTED_SCHEMA_VERSION}"). The dashboard may not display correctly. ` +
      "Update the UI to match the server version.",
    );
  }
}

export function adaptServerPayload(payload: unknown): AdaptedPayload {
  if (payload === null || typeof payload !== "object") {
    throw new Error("Missing websocket payload.");
  }

  const validatedPayload = validateLiveWsPayload(payload);
  warnOnUnknownSchemaVersion(validatedPayload.schema_version);

  return {
    clients: validatedPayload.clients,
    speed_mps: validatedPayload.speed_mps,
    rotational_speeds: validatedPayload.rotational_speeds,
    spectra: adaptSpectra(validatedPayload.spectra),
  };
}
