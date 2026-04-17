export interface RafAnimationCallbacks {
  durationMs: number;
  onFrame: (alpha: number) => void;
  onComplete: () => void;
}

export interface RafAnimation {
  start(): void;
  stop(): void;
}

/**
 * Encapsulates a time-based requestAnimationFrame loop with alpha interpolation.
 * Calling `start()` cancels any in-progress loop and begins a fresh one.
 * Calling `stop()` cancels without invoking `onComplete`.
 */
export function createRafAnimation(callbacks: RafAnimationCallbacks): RafAnimation {
  let handle: number | null = null;

  const stop = (): void => {
    if (handle !== null) {
      window.cancelAnimationFrame(handle);
      handle = null;
    }
  };

  const start = (): void => {
    stop();
    const startedAt = performance.now();
    const animate = (now: number): void => {
      const alpha = Math.min(1, Math.max(0, (now - startedAt) / callbacks.durationMs));
      callbacks.onFrame(alpha);
      if (alpha >= 1) {
        handle = null;
        callbacks.onComplete();
        return;
      }
      handle = window.requestAnimationFrame(animate);
    };
    handle = window.requestAnimationFrame(animate);
  };

  return { start, stop };
}
