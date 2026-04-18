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

export function readDeferredModelValue<T>(
  deferred: ReadonlySignal<ReadonlySignal<T> | null>,
): T | null {
  return deferred.value?.value ?? null;
}

export function readDeferredModel<T>(
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

export interface ModelActionPanelBindings<TModel, TActions> {
  actions: Signal<TActions | null>;
  model: DeferredModelSignal<TModel>;
}

export function createModelActionPanelBindings<TModel, TActions>(): ModelActionPanelBindings<TModel, TActions> {
  return {
    actions: signal<TActions | null>(null),
    model: createDeferredModelSignal<TModel>(),
  };
}
