import { focusManager } from "@tanstack/query-core";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
  createHiddenTabPollingObserverOptions,
  createObservedServerStateQuery,
} from "../src/app/features/server_state_query";
import { signal } from "../src/app/ui_signals";
import { createDeferred, flushAsyncWork } from "./async_test_helpers";
import { createTestQueryClient } from "./query_client_test_support";

async function flushMicrotasks(rounds = 6): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await Promise.resolve();
  }
}

describe("createObservedServerStateQuery", () => {
  afterEach(() => {
    focusManager.setFocused(undefined);
    vi.useRealTimers();
  });

  test("fetch populates the current result data", async () => {
    const query = createObservedServerStateQuery({
      queryClient: createTestQueryClient(),
      queryFn: async () => "ready",
      queryKey: ["test", "manual-fetch"] as const,
    });

    await expect(query.fetch()).resolves.toBe("ready");
    expect(query.result.value.data).toBe("ready");

    query.dispose();
  });

  test("enabled signals gate the initial observed fetch", async () => {
    const enabled = signal(false);
    let calls = 0;
    const query = createObservedServerStateQuery({
      enabled,
      observerOptions: {
        refetchInterval: 500,
        refetchIntervalInBackground: true,
      },
      queryClient: createTestQueryClient(),
      queryFn: async () => {
        calls += 1;
        return calls;
      },
      queryKey: ["test", "refetch"] as const,
    });

    await flushAsyncWork();
    expect(calls).toBe(0);

    enabled.value = true;
    await flushAsyncWork();
    expect(calls).toBe(1);

    query.dispose();
  });

  test("dispose is safe while an observed fetch is still in flight", async () => {
    const response = createDeferred<number>();
    const query = createObservedServerStateQuery({
      observerOptions: {
        refetchInterval: 750,
        refetchIntervalInBackground: true,
      },
      queryClient: createTestQueryClient(),
      queryFn: async () => response.promise,
      queryKey: ["test", "dispose"] as const,
    });

    await flushAsyncWork();
    query.dispose();
    response.resolve(1);
    await flushAsyncWork();
    expect(query.result.value.data).toBeUndefined();
  });

  test("hidden-tab polling pauses until focus returns", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const queryClient = createTestQueryClient();
    const queryKey = ["test", "hidden-tab-polling"] as const;
    queryClient.mount();
    const query = createObservedServerStateQuery({
      observerOptions: createHiddenTabPollingObserverOptions<
        number,
        typeof queryKey
      >(500),
      queryClient,
      queryFn: async () => {
        calls += 1;
        return calls;
      },
      queryKey,
    });

    await flushMicrotasks();
    expect(calls).toBe(1);

    focusManager.setFocused(false);
    await vi.advanceTimersByTimeAsync(2_000);
    await flushMicrotasks();
    expect(calls).toBe(1);

    focusManager.setFocused(true);
    await flushMicrotasks();
    expect(calls).toBe(2);

    query.dispose();
    queryClient.unmount();
  });
});
