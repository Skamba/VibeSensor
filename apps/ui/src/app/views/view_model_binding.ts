import {
  signal,
  type ReadonlySignal,
  type Signal,
} from "../ui_signals";

export type DeferredModelSignal<T> = Signal<ReadonlySignal<T> | null>;

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
