import {
  effect,
  signal,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export interface BoundViewModel<T> {
  readonly model: Signal<T>;
  bind(source: ReadonlySignal<T>): void;
}

export function createBoundViewModel<T>(initialValue: T): BoundViewModel<T> {
  const model = signal(initialValue);
  let stopSync: (() => void) | null = null;

  return {
    model,
    bind(source) {
      stopSync?.();
      stopSync = effect(() => {
        model.value = source.value;
      });
    },
  };
}
