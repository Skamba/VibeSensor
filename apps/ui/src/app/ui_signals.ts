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
