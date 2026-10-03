/**
 * Prepare Vitest's happy-dom document for an isolated mount: start from an empty
 * body and route animation frames through `setTimeout` so fake timers and
 * `flushSignalUpdates()` drive them deterministically. Returns a restore hook.
 */
export function installMountedDomGlobals(): () => void {
  const originalRequestAnimationFrame = globalThis.requestAnimationFrame;
  const originalCancelAnimationFrame = globalThis.cancelAnimationFrame;
  document.body.replaceChildren();
  globalThis.requestAnimationFrame = ((callback: FrameRequestCallback) =>
    setTimeout(
      () => callback(Date.now()),
      0,
    ) as unknown as number) as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = ((handle: number) => {
    clearTimeout(handle);
  }) as typeof cancelAnimationFrame;

  return () => {
    document.body.replaceChildren();
    globalThis.requestAnimationFrame = originalRequestAnimationFrame;
    globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
  };
}
