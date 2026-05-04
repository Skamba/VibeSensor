import type { LoggingStatusPayload } from "../api/types";
import { defaultLocationCodes } from "../constants";
import type {
  AdaptedClient,
  AdaptedPayload,
  RotationalSpeeds,
} from "../transport/live_models";
import { applySpectrumTick, type SpectrumState } from "./spectrum_state";
import { batch, signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface RealtimeStateValue {
  clients: AdaptedClient[];
  selectedClientId: string | null;
  speedMps: number | null;
  rotationalSpeeds: RotationalSpeeds | null;
  loggingStatus: LoggingStatusPayload;
  locationCodes: string[];
}

export type RealtimeState = SignalState<RealtimeStateValue>;

export interface LivePayloadUpdateDeps {
  realtime: RealtimeState;
  spectrum: SpectrumState;
  adaptedPayload: AdaptedPayload;
}

export interface LivePayloadUpdateResult {
  hasSelectedClientChanged: boolean;
  selectedClient: AdaptedClient | undefined;
  hasNewSpectrumFrame: boolean;
}

export function syncSelectedRealtimeClient(realtime: RealtimeState): void {
  const clients = realtime.clients.value;
  const firstConnected = clients.find((client) => Boolean(client.connected));
  if (!realtime.selectedClientId.value && clients.length > 0) {
    realtime.selectedClientId.value = firstConnected
      ? firstConnected.id
      : (clients[0]?.id ?? null);
  }
  if (
    realtime.selectedClientId.value &&
    !clients.some((client) => client.id === realtime.selectedClientId.value)
  ) {
    realtime.selectedClientId.value = firstConnected
      ? firstConnected.id
      : clients.length
        ? (clients[0]?.id ?? null)
        : null;
  }
}

export function applyLivePayloadUpdate(
  deps: LivePayloadUpdateDeps,
): LivePayloadUpdateResult {
  let update!: LivePayloadUpdateResult;
  batch(() => {
    const { realtime, spectrum, adaptedPayload } = deps;
    const previousSelectedClientId = realtime.selectedClientId.value;
    realtime.clients.value = adaptedPayload.clients;
    const spectrumTick = applySpectrumTick(
      spectrum.spectra.value,
      spectrum.hasSpectrumData.value,
      adaptedPayload.spectra,
    );
    spectrum.spectra.value = spectrumTick.spectra;
    syncSelectedRealtimeClient(realtime);
    realtime.speedMps.value = adaptedPayload.speed_mps;
    realtime.rotationalSpeeds.value = adaptedPayload.rotational_speeds;
    spectrum.hasSpectrumData.value = spectrumTick.hasSpectrumData;
    update = {
      hasSelectedClientChanged:
        previousSelectedClientId !== realtime.selectedClientId.value,
      selectedClient: realtime.clients.value.find(
        (client) => client.id === realtime.selectedClientId.value,
      ),
      hasNewSpectrumFrame: spectrumTick.hasNewSpectrumFrame,
    };
  });
  return update;
}

export function createRealtimeState(): RealtimeState {
  return {
    clients: signal<AdaptedClient[]>([]),
    selectedClientId: signal<string | null>(null),
    speedMps: signal<number | null>(null),
    rotationalSpeeds: signal<RotationalSpeeds | null>(null),
    loggingStatus: signal<LoggingStatusPayload>({
      enabled: false,
      run_id: null,
      write_error: null,
      analysis_in_progress: false,
      start_time_utc: null,
      samples_written: 0,
      samples_dropped: 0,
      last_completed_run_id: null,
      last_completed_run_error: null,
      capture_readiness: null,
    }),
    locationCodes: signal(defaultLocationCodes.slice()),
  };
}
