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
  test("drives frames to completion and cancels pending work on stop", () => {
    const { api, cancelled, scheduled } = createFakeRafApi();
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
    animation.stop();
    expect(scheduled.size).toBe(0);
    expect(cancelled).toHaveLength(1);
    expect(completed).toBe(0);

    animation.start();

    const firstFrame = [...scheduled.values()][0];
    expect(firstFrame).toBeDefined();
    scheduled.clear();
    firstFrame?.(performance.now());

    const secondFrame = [...scheduled.values()][0];
    expect(secondFrame).toBeDefined();
    scheduled.clear();
    secondFrame?.(performance.now() + 20);

    expect(alphaFrames).toHaveLength(2);
    expect(alphaFrames[0]).toBeGreaterThanOrEqual(0);
    expect(alphaFrames[0]).toBeLessThan(1);
    expect(alphaFrames[1]).toBe(1);
    expect(completed).toBe(1);
    expect(scheduled.size).toBe(0);
  });
});
