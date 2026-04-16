import { useMemo } from "preact/hooks";
import {
  batch,
  computed,
  effect,
  signal,
  untracked,
  useComputed,
  useSignal,
  useSignalEffect,
  type ReadonlySignal,
  type Signal,
} from "@preact/signals";

type SignalPropertyMap<
  T extends object,
  K extends readonly (keyof T & string)[],
> = {
  readonly [P in K[number]]: ReadonlySignal<T[P]>;
};

type MutableSignalPropertyMap<
  T extends object,
  K extends readonly (keyof T & string)[],
> = {
  -readonly [P in K[number]]: ReadonlySignal<T[P]>;
};

/**
 * Canonical import surface for shared frontend reactive state.
 *
 * Keep component-local ephemeral UI state in hooks. Reach for these exports when
 * state must be shared across runtime, feature, presenter, or view boundaries,
 * and keep effect() limited to narrow imperative integrations such as timers,
 * storage, or external library bridges.
 */
export { batch, computed, effect, signal, untracked, useComputed, useSignal, useSignalEffect };
export type { ReadonlySignal, Signal };

export function useSignalProperties<
  T extends object,
  const K extends readonly (keyof T & string)[],
>(source: ReadonlySignal<T>, keys: K): SignalPropertyMap<T, K> {
  const keysSignature = JSON.stringify(keys);
  return useMemo(() => {
    const properties = {} as MutableSignalPropertyMap<T, K>;
    for (const key of keys) {
      properties[key] = computed(() => source.value[key]);
    }
    return properties;
  }, [source, keysSignature]);
}
