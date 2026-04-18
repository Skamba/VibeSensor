import { signal, type ReadonlySignal } from "../ui_signals";

export interface ApiLoader<TValue> {
  readonly loading: ReadonlySignal<boolean>;
  load(): Promise<TValue | null>;
}

export interface CreateApiLoaderOptions<TValue> {
  beforeLoad?: () => void;
  load: () => Promise<TValue>;
  apply: (value: TValue) => void;
  onError?: (error: unknown) => void;
}

export function createApiLoader<TValue>(
  options: CreateApiLoaderOptions<TValue>,
): ApiLoader<TValue> {
  const loading = signal(false);

  return {
    loading,
    async load(): Promise<TValue | null> {
      loading.value = true;
      options.beforeLoad?.();
      try {
        const value = await options.load();
        options.apply(value);
        return value;
      } catch (error) {
        options.onError?.(error);
        return null;
      } finally {
        loading.value = false;
      }
    },
  };
}
