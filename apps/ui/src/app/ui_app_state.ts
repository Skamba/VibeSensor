import { createRealtimeState, type RealtimeState } from "./realtime_state";
import { analysisTuning, carSettings, speedSettings } from "../settings_store";
import { createShellState, type ShellState } from "./shell_state";
import { createSpectrumState, type SpectrumState } from "./spectrum_state";
import { createTransportState, type TransportState } from "./transport_state";

export type { SignalState } from "./signal_state";
export type { ShellState, ShellStateValue } from "./shell_state";
export type {
  TransportState,
  TransportStateValue,
} from "./transport_state";
export type {
  RealtimeState,
  RealtimeStateValue,
  LivePayloadUpdateDeps,
  LivePayloadUpdateResult,
} from "./realtime_state";
export type {
  ChartBand,
  SpectrumState,
  SpectrumStateValue,
  SpectrumTickUpdate,
} from "./spectrum_state";

/** Pre-rewrite features read the shared settings store through this. */
export interface SettingsState {
  car: typeof carSettings;
  analysis: { vehicleSettings: typeof analysisTuning };
  speed: typeof speedSettings;
}

export interface AppState {
  shell: ShellState;
  transport: TransportState;
  realtime: RealtimeState;
  settings: SettingsState;
  spectrum: SpectrumState;
}

export function createAppState(): AppState {
  return {
    shell: createShellState(),
    transport: createTransportState(),
    realtime: createRealtimeState(),
    settings: {
      car: carSettings,
      analysis: { vehicleSettings: analysisTuning },
      speed: speedSettings,
    },
    spectrum: createSpectrumState(),
  };
}
