import {
  EXPECTED_SCHEMA_VERSION,
  type LiveWsPayload,
} from "./contracts/ws_payload_types";
import type {
  AdaptedClient,
  AdaptedPayload,
  SpectrumClientData,
  SpectrumFrameData,
} from "./transport/live_models";
import { uiLogger } from "./ui_logger";
import { validateLiveWsPayload } from "./ws_payload_validator";

function hasCompleteSpectrumData(
  freq: number[],
  combined: number[],
  strengthMetrics: SpectrumClientData["strength_metrics"] | null,
): strengthMetrics is NonNullable<SpectrumClientData["strength_metrics"]> {
  return (
    freq.length > 0 &&
    combined.length > 0 &&
    strengthMetrics !== null &&
    freq.length === combined.length
  );
}

function adaptSpectra(
  spectra: LiveWsPayload["spectra"],
): AdaptedPayload["spectra"] | null {
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

  const adaptedSpectra: SpectrumFrameData = {
    clients: adaptedClients,
  };
  if (typeof spectra.frame_fingerprint === "string") {
    adaptedSpectra.frame_fingerprint = spectra.frame_fingerprint;
  }
  return adaptedSpectra;
}

let schemaWarningLogged = false;

function warnOnUnknownSchemaVersion(schemaVersion: string): void {
  if (schemaVersion !== EXPECTED_SCHEMA_VERSION && !schemaWarningLogged) {
    schemaWarningLogged = true;
    uiLogger.error(
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
    clients: validatedPayload.clients as AdaptedClient[],
    speed_mps: validatedPayload.speed_mps,
    rotational_speeds: validatedPayload.rotational_speeds
      ? validatedPayload.rotational_speeds
      : null,
    spectra: adaptSpectra(validatedPayload.spectra),
  };
}
