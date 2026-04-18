import { expect, test } from "@playwright/test";

import { signal } from "../src/app/ui_signals";
import {
  bindReplaceableTimerEffect,
  createReplaceableInterval,
  createReplaceableTimeout,
} from "../src/app/timer_cleanup";

test.describe("timer cleanup utilities", () => {
  test("replaceable timeout clears the previous timeout before scheduling a new one", () => {
    let nextHandle = 1;
    const activeHandles = new Set<number>();
    const clearedHandles: number[] = [];
    const timeout = createReplaceableTimeout({
      clearTimeout: ((handle?: ReturnType<typeof setTimeout>) => {
        if (typeof handle !== "number") {
          return;
        }
        activeHandles.delete(handle);
        clearedHandles.push(handle);
      }) as typeof clearTimeout,
      setTimeout: ((callback: TimerHandler, delay?: number) => {
        void callback;
        void delay;
        const handle = nextHandle;
        nextHandle += 1;
        activeHandles.add(handle);
        return handle as unknown as ReturnType<typeof setTimeout>;
      }) as typeof setTimeout,
    });

    timeout.replace(() => undefined, 500);
    timeout.replace(() => undefined, 750);

    expect(Array.from(activeHandles)).toEqual([2]);
    expect(clearedHandles).toEqual([1]);

    timeout.clear();

    expect(activeHandles.size).toBe(0);
    expect(clearedHandles).toEqual([1, 2]);
  });

  test("replaceable interval clears the previous interval before starting a new one", () => {
    let nextHandle = 1;
    const activeHandles = new Set<number>();
    const clearedHandles: number[] = [];
    const interval = createReplaceableInterval({
      clearInterval: ((handle?: ReturnType<typeof setInterval>) => {
        if (typeof handle !== "number") {
          return;
        }
        activeHandles.delete(handle);
        clearedHandles.push(handle);
      }) as typeof clearInterval,
      setInterval: ((callback: TimerHandler, delay?: number) => {
        void callback;
        void delay;
        const handle = nextHandle;
        nextHandle += 1;
        activeHandles.add(handle);
        return handle as unknown as ReturnType<typeof setInterval>;
      }) as typeof setInterval,
    });

    interval.replace(() => undefined, 1_000);
    interval.replace(() => undefined, 2_000);

    expect(Array.from(activeHandles)).toEqual([2]);
    expect(clearedHandles).toEqual([1]);

    interval.clear();

    expect(activeHandles.size).toBe(0);
    expect(clearedHandles).toEqual([1, 2]);
  });

  test("timer effect binds and clears a replaceable interval from signal state", () => {
    let nextHandle = 1;
    const activeHandles = new Set<number>();
    const clearedHandles: number[] = [];
    const enabled = signal(false);
    const tickLog: string[] = [];
    const interval = createReplaceableInterval({
      clearInterval: ((handle?: ReturnType<typeof setInterval>) => {
        if (typeof handle !== "number") {
          return;
        }
        activeHandles.delete(handle);
        clearedHandles.push(handle);
      }) as typeof clearInterval,
      setInterval: ((callback: TimerHandler, delay?: number) => {
        void callback;
        void delay;
        const handle = nextHandle;
        nextHandle += 1;
        activeHandles.add(handle);
        return handle as unknown as ReturnType<typeof setInterval>;
      }) as typeof setInterval,
    });

    bindReplaceableTimerEffect(interval, () => {
      if (!enabled.value) {
        return null;
      }
      return {
        fireImmediately: true,
        delayMs: 1_000,
        callback: () => {
          tickLog.push("tick");
        },
      };
    });

    expect(activeHandles.size).toBe(0);
    expect(tickLog).toEqual([]);

    enabled.value = true;
    expect(tickLog).toEqual(["tick"]);
    expect(Array.from(activeHandles)).toEqual([1]);

    enabled.value = false;
    expect(activeHandles.size).toBe(0);
    expect(clearedHandles).toEqual([1]);
  });
});
