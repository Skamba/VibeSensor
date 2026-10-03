import { effect, signal, type ReadonlySignal } from "@preact/signals";

const pageVisible = signal(globalThis.document?.visibilityState !== "hidden");
globalThis.document?.addEventListener("visibilitychange", () => {
  pageVisible.value = document.visibilityState !== "hidden";
});

export interface Poll {
  /** Loads now (even while inactive) and restarts the interval. */
  refresh(): Promise<void>;
  stop(): void;
}

/**
 * Polls `load` while `active` is true and the page is visible: once on
 * activation, then `intervalMs` after each result. Only the latest load's
 * result (or error) is delivered, so a slow older request never overwrites
 * newer data.
 */
export function poll<T>(options: {
  active: ReadonlySignal<boolean>;
  intervalMs: number | ((last: T | undefined) => number);
  load: () => Promise<T>;
  onData: (data: T) => void;
  onError?: (error: unknown) => void;
}): Poll {
  let last: T | undefined;
  let latest = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const interval = () =>
    typeof options.intervalMs === "number"
      ? options.intervalMs
      : options.intervalMs(last);

  async function refresh(): Promise<void> {
    clearTimeout(timer);
    const request = ++latest;
    try {
      const data = await options.load();
      if (request === latest) {
        last = data;
        options.onData(data);
      }
    } catch (error) {
      if (request === latest) {
        options.onError?.(error);
      }
    }
    if (request === latest && options.active.peek() && pageVisible.peek()) {
      timer = setTimeout(() => void refresh(), interval());
    }
  }

  const stopEffect = effect(() => {
    if (options.active.value && pageVisible.value) {
      void refresh();
    } else {
      clearTimeout(timer);
    }
  });
  return {
    refresh,
    stop() {
      stopEffect();
      clearTimeout(timer);
      latest += 1;
    },
  };
}
