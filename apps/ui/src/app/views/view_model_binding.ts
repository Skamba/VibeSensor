import {
  signal,
  useComputed,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export type DeferredModelSignal<T> = Signal<ReadonlySignal<T> | null>;

export function createDeferredModelSignal<T>(): DeferredModelSignal<T> {
  return signal<ReadonlySignal<T> | null>(null);
}

function readDeferredModelValue<T>(
  deferred: ReadonlySignal<ReadonlySignal<T> | null>,
): T | null {
  return deferred.value?.value ?? null;
}

function readDeferredModel<T>(
  deferred: ReadonlySignal<ReadonlySignal<T> | null>,
  defaultValue: T,
): T {
  return readDeferredModelValue(deferred) ?? defaultValue;
}

export function useDeferredModel<T>(
  deferred: ReadonlySignal<ReadonlySignal<T> | null>,
  defaultValue: T,
): ReadonlySignal<T> {
  return useComputed(() => readDeferredModel(deferred, defaultValue));
}
