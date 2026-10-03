import {
  activeView,
  speedUnit,
  type SpeedUnit,
  type ViewId,
} from "../app_store";
import { lang, type Lang } from "../i18n";
import type { SignalState } from "./signal_state";

export interface ShellStateValue {
  lang: Lang;
  speedUnit: SpeedUnit;
  activeViewId: ViewId;
}

export type ShellState = SignalState<ShellStateValue>;

/** Pre-rewrite features read the shell's module-level signals through this. */
export function createShellState(): ShellState {
  return { lang, speedUnit, activeViewId: activeView };
}
