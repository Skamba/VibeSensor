import {
  signal,
  useComputed,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export interface DeferredViewModel<T> {
  readonly model: Signal<ReadonlySignal<T> | null>;
  bind(source: ReadonlySignal<T>): void;
}

export function createDeferredViewModel<T>(): DeferredViewModel<T> {
  const model = signal<ReadonlySignal<T> | null>(null);
  return {
    model,
    bind(source) {
      model.value = source;
    },
  };
}

export function useDeferredViewModel<T>(
  source: ReadonlySignal<ReadonlySignal<T> | null>,
  initialValue: T,
): ReadonlySignal<T> {
  return useComputed(() => source.value?.value ?? initialValue);
}
