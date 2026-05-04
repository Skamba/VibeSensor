import { signal } from "./ui_signals";
import type { SignalState } from "./signal_state";

export interface ShellStateValue {
  lang: string;
  speedUnit: string;
  activeViewId: string;
}

export type ShellState = SignalState<ShellStateValue>;

export function createShellState(): ShellState {
  return {
    lang: signal("en"),
    speedUnit: signal("kmh"),
    activeViewId: signal("dashboardView"),
  };
}
