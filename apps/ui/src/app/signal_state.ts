import type { Signal } from "./ui_signals";

export type SignalState<T extends object> = {
  [K in keyof T]: Signal<T[K]>;
};
