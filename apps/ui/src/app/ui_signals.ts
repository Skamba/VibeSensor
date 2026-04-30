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
export {
  batch,
  computed,
  effect,
  signal,
  untracked,
  useComputed,
  useSignalEffect,
};
export type { ReadonlySignal, Signal };

const signalPropertiesCache = new WeakMap<object, WeakMap<object, object>>();

function getOrCreateSignalPropertyMap<
  T extends object,
  const K extends readonly (keyof T & string)[],
>(source: ReadonlySignal<T>, keys: K): SignalPropertyMap<T, K> {
  const sourceCacheKey = source as object;
  let sourceCache = signalPropertiesCache.get(sourceCacheKey);
  if (!sourceCache) {
    sourceCache = new WeakMap<object, object>();
    signalPropertiesCache.set(sourceCacheKey, sourceCache);
  }

  const keysCacheKey = keys as object;
  const cachedProperties = sourceCache.get(keysCacheKey);
  if (cachedProperties) {
    return cachedProperties as SignalPropertyMap<T, K>;
  }

  const properties = {} as MutableSignalPropertyMap<T, K>;
  for (const key of keys) {
    properties[key] = computed(() => source.value[key]);
  }
  sourceCache.set(keysCacheKey, properties);
  return properties;
}

export function useSignalProperties<
  T extends object,
  const K extends readonly (keyof T & string)[],
>(source: ReadonlySignal<T>, keys: K): SignalPropertyMap<T, K> {
  return getOrCreateSignalPropertyMap(source, keys);
}

export function effectOnChange<T>(
  source: ReadonlySignal<T>,
  callback: (value: T, previousValue: T) => void,
): () => void {
  let previousValue = source.peek();
  return effect(() => {
    const nextValue = source.value;
    if (Object.is(nextValue, previousValue)) {
      return;
    }
    const oldValue = previousValue;
    previousValue = nextValue;
    callback(nextValue, oldValue);
  });
}
