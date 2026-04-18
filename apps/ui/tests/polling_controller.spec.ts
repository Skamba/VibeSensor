import { expect, test } from "@playwright/test";

import { createPollingController } from "../src/app/features/polling_controller";
import { signal } from "../src/app/ui_signals";
import { createDeferred, flushAsyncWork, installTimerHarness } from "./async_test_helpers";

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

  test("enabled signals start and stop the poll loop without manual lifecycle calls", async () => {
    const timers = installTimerHarness();
    const enabled = signal(false);
    let pollCalls = 0;

    createPollingController({
      enabled,
      poll: async () => {
        pollCalls += 1;
        return 500;
      },
      onErrorDelayMs: 2_000,
    });

    try {
      await flushAsyncWork();
      expect(pollCalls).toBe(0);
      expect(timers.pendingDelays()).toEqual([]);

      enabled.value = true;
      await flushAsyncWork();
      expect(pollCalls).toBe(1);
      expect(timers.pendingDelays()).toEqual([500]);

      enabled.value = false;
      await flushAsyncWork();
      expect(timers.pendingDelays()).toEqual([]);
    } finally {
      timers.restore();
    }
  });

  test("dispose tears down enabled-signal polling permanently", async () => {
    const timers = installTimerHarness();
    const enabled = signal(true);
    let pollCalls = 0;
    const controller = createPollingController({
      enabled,
      poll: async () => {
        pollCalls += 1;
        return 500;
      },
      onErrorDelayMs: 2_000,
    });

    try {
      await flushAsyncWork();
      expect(pollCalls).toBe(1);
      expect(timers.pendingDelays()).toEqual([500]);

      controller.dispose();
      expect(timers.pendingDelays()).toEqual([]);

      enabled.value = false;
      enabled.value = true;
      await flushAsyncWork();
      expect(pollCalls).toBe(1);
      expect(timers.pendingDelays()).toEqual([]);
    } finally {
      timers.restore();
    }
  });
});
