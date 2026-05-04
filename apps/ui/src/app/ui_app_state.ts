import { createHistoryState, type HistoryState } from "./history_state";
import { createRealtimeState, type RealtimeState } from "./realtime_state";
import { createSettingsState, type SettingsState } from "./settings_state";
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
  HistoryState,
  HistoryStateValue,
  RunDetail,
} from "./history_state";
export type {
  CarAspectSettings,
  AnalysisTuningSettings,
  VehicleSettings,
  CarSettingsValue,
  AnalysisSettingsValue,
  SpeedSettingsValue,
  CarSettingsState,
  AnalysisSettingsState,
  SpeedSettingsState,
  SettingsState,
} from "./settings_state";
export type {
  ChartBand,
  SpectrumState,
  SpectrumStateValue,
  SpectrumTickUpdate,
} from "./spectrum_state";

export interface AppState {
  shell: ShellState;
  transport: TransportState;
  realtime: RealtimeState;
  history: HistoryState;
  settings: SettingsState;
  spectrum: SpectrumState;
}

export function createAppState(): AppState {
  return {
    shell: createShellState(),
    transport: createTransportState(),
    realtime: createRealtimeState(),
    history: createHistoryState(),
    settings: createSettingsState(),
    spectrum: createSpectrumState(),
  };
}
