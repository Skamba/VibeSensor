import { expect, test } from "@playwright/test";

import { createPollingController } from "../src/app/features/polling_controller";

type TimerHarness = {
  pendingDelays(): number[];
  restore(): void;
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve(value: T): void;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function installTimerHarness(): TimerHarness {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextId = 1;
  const active = new Map<number, number>();

  globalThis.setTimeout = ((handler: TimerHandler, delay?: number) => {
    const id = nextId;
    nextId += 1;
    active.set(id, Number(delay ?? 0));
    void handler;
    return id as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout;

  globalThis.clearTimeout = ((timeoutId?: ReturnType<typeof setTimeout>) => {
    if (typeof timeoutId !== "number") return;
    active.delete(timeoutId);
  }) as typeof clearTimeout;

  return {
    pendingDelays(): number[] {
      return Array.from(active.values()).sort((left, right) => left - right);
    },
    restore(): void {
      globalThis.setTimeout = originalSetTimeout;
      globalThis.clearTimeout = originalClearTimeout;
    },
  };
}

async function flushAsyncWork(rounds = 12): Promise<void> {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise<void>((resolve) => {
      setImmediate(resolve);
    });
  }
}

test.describe("createPollingController", () => {
  test("restart replaces the previous timer instead of keeping two poll chains alive", async () => {
    const timers = installTimerHarness();
    let pollCalls = 0;
    const controller = createPollingController({
      poll: async () => {
        pollCalls += 1;
        return 500;
      },
      onErrorDelayMs: 2_000,
    });

    try {
      controller.start();
      await flushAsyncWork();
      expect(pollCalls).toBe(1);
      expect(timers.pendingDelays()).toEqual([500]);

      controller.restart();
      await flushAsyncWork();
      expect(pollCalls).toBe(2);
      expect(timers.pendingDelays()).toEqual([500]);
    } finally {
      timers.restore();
    }
  });

  test("stop prevents an in-flight poll from reviving the loop", async () => {
    const timers = installTimerHarness();
    const pollDeferred = createDeferred<number>();
    let pollCalls = 0;
    const controller = createPollingController({
      poll: async () => {
        pollCalls += 1;
        if (pollCalls === 1) {
          return pollDeferred.promise;
        }
        return 750;
      },
      onErrorDelayMs: 2_000,
    });

    try {
      controller.start();
      await flushAsyncWork();
      expect(pollCalls).toBe(1);
      expect(timers.pendingDelays()).toEqual([]);

      controller.stop();
      pollDeferred.resolve(750);
      await flushAsyncWork();
      expect(timers.pendingDelays()).toEqual([]);
    } finally {
      timers.restore();
    }
  });

  test("errors schedule the configured retry delay", async () => {
    const timers = installTimerHarness();
    const controller = createPollingController({
      poll: async () => {
        throw new Error("temporary failure");
      },
      onErrorDelayMs: 3_000,
    });

    try {
      controller.start();
      await flushAsyncWork();
      expect(timers.pendingDelays()).toEqual([3_000]);
    } finally {
      timers.restore();
    }
  });
});
