import { describe, expect, test } from "vitest";
import { createReplaceableTimeout } from "../src/timer_cleanup";

describe("timer cleanup utilities", () => {
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
});
