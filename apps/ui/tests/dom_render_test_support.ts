import { flushSignalUpdates } from "./async_test_helpers";

export type MountedSignalView<TView> = {
  cleanup(): void;
  flush(rounds?: number): Promise<void>;
  host: HTMLElement;
  view: TView;
};

export async function mountSignalView<TView>(
  loadMount: () =>
    | Promise<(host: HTMLElement) => TView>
    | ((host: HTMLElement) => TView),
): Promise<MountedSignalView<TView>>;
export async function mountSignalView<TView>(
  loadMount: () =>
    | Promise<(host: HTMLElement, view: TView) => void>
    | ((host: HTMLElement, view: TView) => void),
  createView: () => TView,
): Promise<MountedSignalView<TView>>;
export async function mountSignalView<TView>(
  loadMount: () =>
    | Promise<
        | ((host: HTMLElement) => TView)
        | ((host: HTMLElement, view: TView) => void)
      >
    | ((host: HTMLElement) => TView)
    | ((host: HTMLElement, view: TView) => void),
  createView?: () => TView,
): Promise<MountedSignalView<TView>> {
  const restoreDom = installMountedDomGlobals();
  const host = globalThis.document.createElement("div");
  globalThis.document.body.appendChild(host);
  let cleanedUp = false;

  try {
    const { render } = await import("preact");
    const mount = await loadMount();
    if (createView) {
      const view = createView();
      (mount as (host: HTMLElement, view: TView) => void)(host, view);
      return {
        cleanup(): void {
          if (cleanedUp) {
            return;
          }
          cleanedUp = true;
          render(null, host);
          host.remove();
          restoreDom();
        },
        flush(rounds = 12): Promise<void> {
          return flushSignalUpdates(rounds);
        },
        host,
        view,
      };
    }
    const view = (mount as (host: HTMLElement) => TView)(host);
    return {
      cleanup(): void {
        if (cleanedUp) {
          return;
        }
        cleanedUp = true;
        render(null, host);
        host.remove();
        restoreDom();
      },
      flush(rounds = 12): Promise<void> {
        return flushSignalUpdates(rounds);
      },
      host,
      view,
    };
  } catch (error) {
    host.remove();
    restoreDom();
    throw error;
  }
}

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
