import {
  QueryObserver,
  type FetchQueryOptions,
  type QueryKey,
  type QueryObserverOptions,
  type QueryObserverResult,
  type QueryClient,
  type Updater,
} from "@tanstack/query-core";

import { effect, signal, type ReadonlySignal } from "../ui_signals";

interface CreateObservedServerStateQueryOptions<
  TData,
  TQueryKey extends QueryKey,
> {
  enabled?: ReadonlySignal<boolean>;
  observerOptions?: Omit<
    QueryObserverOptions<TData, unknown, TData, TData, TQueryKey>,
    "enabled" | "queryFn" | "queryKey"
  >;
  onData?: (data: TData) => void;
  onError?: (error: unknown) => void;
  queryClient: QueryClient;
  queryFn: NonNullable<
    QueryObserverOptions<TData, unknown, TData, TData, TQueryKey>["queryFn"]
  >;
  queryKey: TQueryKey;
}

export interface ObservedServerStateQuery<TData> {
  readonly result: ReadonlySignal<QueryObserverResult<TData, unknown>>;
  dispose(): void;
  fetch(): Promise<TData>;
  invalidate(): Promise<void>;
  setData(updater: Updater<TData | undefined, TData | undefined>): void;
}

export function createHiddenTabPollingObserverOptions<
  TData,
  TQueryKey extends QueryKey = QueryKey,
>(
  refetchInterval: NonNullable<
    QueryObserverOptions<TData, unknown, TData, TData, TQueryKey>["refetchInterval"]
  >,
): Pick<
  QueryObserverOptions<TData, unknown, TData, TData, TQueryKey>,
  "refetchInterval" | "refetchIntervalInBackground" | "refetchOnWindowFocus"
> {
  return {
    refetchInterval,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
  };
}

export function createObservedServerStateQuery<
  TData,
  TQueryKey extends QueryKey = QueryKey,
>(
  options: CreateObservedServerStateQueryOptions<TData, TQueryKey>,
): ObservedServerStateQuery<TData> {
  const {
    enabled,
    observerOptions,
    onData,
    onError,
    queryClient,
    queryFn,
    queryKey,
  } = options;

  function observerConfig(): QueryObserverOptions<TData, unknown, TData, TData, TQueryKey> {
    return {
      ...observerOptions,
      enabled: enabled?.value ?? true,
      queryFn,
      queryKey,
    };
  }

  function fetchConfig(): FetchQueryOptions<TData, unknown, TData, TQueryKey> {
    return {
      ...observerOptions,
      queryFn,
      queryKey,
    };
  }

  const observer = new QueryObserver<TData, unknown, TData, TData, TQueryKey>(
    queryClient,
    observerConfig(),
  );
  const result = signal(observer.getCurrentResult());
  let lastData = result.peek().data;
  let lastError = result.peek().error;

  function applyResult(next: QueryObserverResult<TData, unknown>): void {
    result.value = next;
    if (next.data !== undefined && next.data !== lastData) {
      lastData = next.data;
      onData?.(next.data);
    }
    if (next.error != null && next.error !== lastError) {
      lastError = next.error;
      onError?.(next.error);
      return;
    }
    if (next.error == null) {
      lastError = null;
    }
  }

  const unsubscribe = observer.subscribe(applyResult);
  applyResult(observer.getCurrentResult());
  const disposeEnabledSync = enabled
    ? effect(() => {
      observer.setOptions(observerConfig());
    })
    : null;

  return {
    result,
    dispose(): void {
      unsubscribe();
      disposeEnabledSync?.();
      observer.destroy();
    },
    fetch(): Promise<TData> {
      return queryClient.fetchQuery(fetchConfig());
    },
    invalidate(): Promise<void> {
      return queryClient.invalidateQueries({ queryKey });
    },
    setData(updater): void {
      queryClient.setQueryData<TData>(queryKey, updater);
    },
  };
}
