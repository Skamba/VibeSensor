import { describe, expect, test } from "vitest";
import { createRafAnimation, type RafApi } from "../src/app/dom/raf_animation";

function createFakeRafApi() {
  let nextHandle = 1;
  const scheduled = new Map<number, FrameRequestCallback>();
  const cancelled: number[] = [];

  const api: RafApi = {
    cancelAnimationFrame(handle: number): void {
      cancelled.push(handle);
      scheduled.delete(handle);
    },
    requestAnimationFrame(callback: FrameRequestCallback): number {
      const handle = nextHandle;
      nextHandle += 1;
      scheduled.set(handle, callback);
      return handle;
    },
  };

  return { api, cancelled, scheduled };
}

describe("createRafAnimation", () => {
  test("cancels the in-flight frame before restarting or stopping", () => {
    const { api, cancelled, scheduled } = createFakeRafApi();
    const animation = createRafAnimation(
      {
        durationMs: 250,
        onComplete: () => undefined,
        onFrame: () => undefined,
      },
      api,
    );

    animation.start();
    expect(Array.from(scheduled.keys())).toEqual([1]);

    animation.start();
    expect(cancelled).toEqual([1]);
    expect(Array.from(scheduled.keys())).toEqual([2]);

    animation.stop();
    expect(cancelled).toEqual([1, 2]);
    expect(scheduled.size).toBe(0);
  });

  test("drives frames and completion through the injected raf api", () => {
    const { api, scheduled } = createFakeRafApi();
    const alphaFrames: number[] = [];
    let completed = 0;
    const animation = createRafAnimation(
      {
        durationMs: 10,
        onComplete: () => {
          completed += 1;
        },
        onFrame: (alpha) => {
          alphaFrames.push(alpha);
        },
      },
      api,
    );

    animation.start();

    const firstFrame = scheduled.get(1);
    expect(firstFrame).toBeDefined();
    scheduled.delete(1);
    firstFrame?.(performance.now());

    const secondFrame = scheduled.get(2);
    expect(secondFrame).toBeDefined();
    scheduled.delete(2);
    secondFrame?.(performance.now() + 20);

    expect(alphaFrames).toHaveLength(2);
    expect(alphaFrames[0]).toBeGreaterThanOrEqual(0);
    expect(alphaFrames[0]).toBeLessThan(1);
    expect(alphaFrames[1]).toBe(1);
    expect(completed).toBe(1);
    expect(scheduled.size).toBe(0);
  });
});
