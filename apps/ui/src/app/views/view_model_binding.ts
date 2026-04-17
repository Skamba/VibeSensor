import {
  signal,
  useComputed,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export type DeferredModelSignal<T> = Signal<ReadonlySignal<T> | null>;

export interface DeferredViewModel<T> {
  readonly model: DeferredModelSignal<T>;
  bind(source: ReadonlySignal<T>): void;
}

export function createDeferredModelSignal<T>(): DeferredModelSignal<T> {
  return signal<ReadonlySignal<T> | null>(null);
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

export function createDeferredViewModel<T>(): DeferredViewModel<T> {
  const model = createDeferredModelSignal<T>();
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
